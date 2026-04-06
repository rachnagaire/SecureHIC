"""
pipeline.py
SecureHIC — Full Pipeline: Multi-User Fetch → Bronze → Silver → ML(BQ) → Gold

Flow:
  Step 1+2 — Fetch all users via browser OAuth, combine into one bundle
  Step 3   — Bronze  : raw + PQC/Classical encrypted → GCS
              + benchmarking summary/raw JSON written locally by run_benchmark()
  Step 4   — Silver  : parse + encrypt PHI + anonymize → GCS + local CSV
  Step 5   — ML push : ml_df (fraud-detection-ready, zero PHI) → BigQuery as ml_features
  Step 6   — Gold    : aggregate analytics → GCS only

BigQuery has exactly ONE table: ml_features
  - All fraud-detection columns present, no PHI, no encrypted blobs
  - This is what download_ml_features.py pulls for the fraud detection notebook
"""

import os
import json
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from api_client import get_oauth_token, fetch_full_fhir_bundle
from benchmark_plot import run_benchmark
from silver import process_to_silver
from fhir_parser import anonymize_patient_id, make_ml_features
from cloud_upload import (
    upload_raw_to_bronze,
    upload_silver_to_gcs,
    upload_gold_to_gcs,
    load_to_bigquery,
)
from audit import write_audit
from config import BQ_PROJECT, BQ_DATASET


# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────

TOP_USERS = [
    ("BBUser09338", "PW09338!"),
    ("BBUser02239", "PW02239!"),
    ("BBUser02950", "PW02950!"),
    ("BBUser01581", "PW01581!"),
]


# ─────────────────────────────────────────────
# Local helpers
# ─────────────────────────────────────────────

def _project_root_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _local_data_dir() -> str:
    data_dir = os.path.join(_project_root_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _local_outputs_dir() -> str:
    outputs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    return outputs_dir


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _save_json_locally(data: dict, filename: str) -> str:
    path = os.path.join(_local_data_dir(), filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[OK] Saved locally: {path}")
    return path


def save_silver_csv_locally(silver_df: pd.DataFrame) -> str:
    path = os.path.join(_local_data_dir(), f"cms_fhir_silver_{_ts()}.csv")
    df_copy = silver_df.copy()

    for col in df_copy.columns:
        df_copy[col] = df_copy[col].apply(
            lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x
        )

    df_copy.to_csv(path, index=False)
    print(f"[OK] Silver CSV saved locally: {path}")
    return path


def save_ml_csv_locally(ml_df: pd.DataFrame) -> str:
    path = os.path.join(_local_data_dir(), f"ml_features_{_ts()}.csv")
    ml_df.to_csv(path, index=False)
    print(f"[OK] ML features CSV saved locally: {path}")
    return path


def _normalize_benchmark_result(bench_result: dict | None) -> dict:
    """
    Normalize old/new benchmark return structures into one predictable dict.

    Expected new style from run_benchmark():
    {
        "raw_path": ".../benchmark_raw.json",
        "summary_path": ".../benchmark_summary.json",
        "summary": {...},
        "plot_paths": {...}   # optional
    }

    Also tolerates older return values so pipeline doesn't break.
    """
    bench_result = bench_result if isinstance(bench_result, dict) else {}
    summary = bench_result.get("summary", {})

    normalized = {
        "raw_path": bench_result.get("raw_path"),
        "summary_path": bench_result.get("summary_path"),
        "summary": summary if isinstance(summary, dict) else {},
        "plot_paths": bench_result.get("plot_paths", {}),
    }

    # Backward compatibility: older version may return summary fields at top level
    if not normalized["summary"]:
        summary_keys = [
            "rounds",
            "avg_classical_encrypt",
            "avg_pqc_encrypt",
            "avg_classical_decrypt",
            "avg_pqc_decrypt",
            "avg_sequential_pipeline",
            "avg_parallel_pipeline",
            "speedup",
            "original_size_kb",
            "classical_size_kb",
            "pqc_size_kb",
            "worker_counts",
            "worker_times",
            "stage_labels",
            "stage_times",
        ]
        normalized["summary"] = {
            k: bench_result[k] for k in summary_keys if k in bench_result
        }

    # Backward compatibility for plot fields
    if not normalized["plot_paths"]:
        plot_keys = [
            "crypto_plot",
            "decrypt_plot",
            "size_plot",
            "speedup_plot",
            "scalability_plot",
            "pipeline_plot",
        ]
        normalized["plot_paths"] = {
            k: bench_result[k] for k in plot_keys if k in bench_result
        }

    return normalized


# ─────────────────────────────────────────────
# Gold aggregation
# ─────────────────────────────────────────────

def process_to_gold(silver_df: pd.DataFrame) -> pd.DataFrame:
    df = silver_df.copy()

    phi_cols = [
        "patient_reference", "diagnosis_codes", "procedure_codes",
        "provider", "facility", "patient_name", "patient_dob",
        "patient_gender", "patient_zip", "patient_state",
    ]
    df = df.drop(columns=[c for c in phi_cols if c in df.columns], errors="ignore")

    numeric_cols = [
        "payment_amount", "total_charged", "total_line_items",
        "num_diagnosis_codes", "num_procedure_codes",
        "avg_payment_per_line", "avg_charge_per_line",
        "line_submitted_total", "line_eligible_total", "line_benefit_total",
        "line_paid_to_provider_total", "line_paid_to_patient_total",
        "line_deductible_total", "line_coinsurance_total",
        "line_priorpayer_total", "line_all_adjudication_total",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    gold_frames = []

    if "claim_type" in df.columns:
        agg_map = {
            "claim_count":   ("claim_id", "count"),
            "total_payment": ("payment_amount", "sum"),
            "avg_payment":   ("payment_amount", "mean"),
            "total_charged": ("total_charged", "sum"),
        }
        if "total_line_items" in df.columns:
            agg_map["avg_line_items"] = ("total_line_items", "mean")
        if "num_diagnosis_codes" in df.columns:
            agg_map["avg_diagnosis_codes"] = ("num_diagnosis_codes", "mean")
        if "num_procedure_codes" in df.columns:
            agg_map["avg_procedure_codes"] = ("num_procedure_codes", "mean")

        by_claim_type = (
            df.groupby("claim_type", dropna=False)
            .agg(**agg_map)
            .reset_index()
            .round(2)
        )
        by_claim_type["aggregation"] = "by_claim_type"
        gold_frames.append(by_claim_type)

    if "payer" in df.columns:
        by_payer = (
            df.groupby("payer", dropna=False)
            .agg(
                claim_count=("claim_id", "count"),
                total_payment=("payment_amount", "sum"),
                avg_payment=("payment_amount", "mean"),
                total_charged=("total_charged", "sum"),
            )
            .reset_index()
            .round(2)
        )
        by_payer["aggregation"] = "by_payer"
        gold_frames.append(by_payer)

    if "service_date_start" in df.columns:
        df["service_date"] = pd.to_datetime(
            df["service_date_start"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")

        daily_volume = (
            df.groupby("service_date", dropna=False)
            .agg(
                claim_count=("claim_id", "count"),
                total_payment=("payment_amount", "sum"),
                total_charged=("total_charged", "sum"),
            )
            .reset_index()
            .round(2)
        )
        daily_volume["aggregation"] = "daily_volume"
        gold_frames.append(daily_volume)

    if not gold_frames:
        print("[WARN] No Gold aggregations produced.")
        return pd.DataFrame()

    return pd.concat(gold_frames, ignore_index=True)


# ─────────────────────────────────────────────
# Stage 1+2 — Multi-user fetch + combine
# ─────────────────────────────────────────────

def _fetch_and_combine_stage() -> tuple[dict, str]:
    print("\n" + "=" * 60)
    print("   Step 1+2 — Multi-User Fetch & Combine")
    print("=" * 60)

    all_entries = []
    failed_users = []

    for idx, (username, password) in enumerate(TOP_USERS, start=1):
        print(f"\n[User {idx}/{len(TOP_USERS)}] {username}")
        print("  Browser will open — log in and approve access.")
        print(f"  Username : {username}  |  Password : {password}")

        try:
            token = get_oauth_token(username_hint=username, password_hint=password)
            bundle = fetch_full_fhir_bundle(token)
            entries = bundle.get("entry", [])

            all_entries.extend(entries)

            print(f"  [OK] {len(entries)} entries  (total so far: {len(all_entries)})")
            write_audit("FETCH_USER", f"SUCCESS - {username} - {len(entries)} entries")

        except Exception as e:
            print(f"  [WARN] {username} failed: {e}")
            write_audit("FETCH_USER", f"FAIL - {username} - {e}")
            failed_users.append((username, str(e)))

    if not all_entries:
        raise RuntimeError("No entries fetched — cannot continue.")

    if failed_users:
        for username, reason in failed_users:
            print(f"  [FAIL] {username}: {reason}")

    combined_bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(all_entries),
        "entry": all_entries,
    }

    combined_path = _save_json_locally(
        combined_bundle,
        f"cms_fhir_bundle_combined_{_ts()}.json"
    )

    resource_types: dict[str, int] = {}
    for entry in all_entries:
        rt = entry.get("resource", {}).get("resourceType", "UNKNOWN")
        resource_types[rt] = resource_types.get(rt, 0) + 1

    print(f"\n  Total entries     : {len(all_entries):,}")
    print(f"  Resource breakdown: {resource_types}")
    write_audit("COMBINE_BUNDLES", f"SUCCESS - {len(all_entries)} entries | {resource_types}")

    return combined_bundle, combined_path


# ─────────────────────────────────────────────
# Stage 3 — Bronze
# ─────────────────────────────────────────────

def _bronze_stage(raw_bundle: dict, benchmark_rounds: int = 4) -> dict:
    print("\n" + "=" * 60)
    print("   Step 3 — Bronze  →  GCS")
    print("=" * 60)

    start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=2) as ex:
        future_upload = ex.submit(upload_raw_to_bronze, raw_bundle)
        future_bench = ex.submit(run_benchmark, raw_bundle, benchmark_rounds)

        upload_result = future_upload.result()
        bench_result = future_bench.result()

    elapsed = round(time.perf_counter() - start, 3)

    upload_result = upload_result if isinstance(upload_result, dict) else {}
    benchmark_info = _normalize_benchmark_result(bench_result)

    write_audit(
        "BRONZE_COMPLETE",
        f"SUCCESS - bronze upload + benchmark in {elapsed}s"
    )

    print(f"[Bronze] {elapsed}s")
    print(f"  Raw bundle path     : {upload_result.get('raw_path')}")
    print(f"  PQC encrypted path  : {upload_result.get('pqc_path')}")
    print(f"  Classical enc path  : {upload_result.get('classical_path')}")
    print(f"  Benchmark raw JSON  : {benchmark_info.get('raw_path')}")
    print(f"  Benchmark summary   : {benchmark_info.get('summary_path')}")

    return {
        "upload": upload_result,
        "benchmark": benchmark_info,
        "elapsed_seconds": elapsed,
    }


# ─────────────────────────────────────────────
# Stage 4 — Silver  (GCS + local only)
# ─────────────────────────────────────────────

def _silver_stage(raw_bundle: dict) -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    print("\n" + "=" * 60)
    print("   Step 4 — Silver  →  GCS + local CSV")
    print("   (PHI-encrypted silver stays OFF BigQuery)")
    print("=" * 60)

    t0 = time.perf_counter()

    silver_df = process_to_silver(raw_bundle, max_workers=4)
    silver_df = anonymize_patient_id(silver_df)
    ml_df = make_ml_features(silver_df)

    local_silver_csv = save_silver_csv_locally(silver_df)
    local_ml_csv = save_ml_csv_locally(ml_df)

    try:
        upload_silver_to_gcs(silver_df)
        print("[Silver] GCS upload done")
    except Exception as e:
        print(f"[WARN] Silver GCS upload failed: {e}")
        write_audit("SILVER_WARN", f"silver_gcs - {e}")

    elapsed = round(time.perf_counter() - t0, 3)
    write_audit("SILVER_COMPLETE", f"SUCCESS - {len(silver_df)} rows in {elapsed}s")
    print(f"[Silver] {len(silver_df):,} rows in {elapsed}s")

    return silver_df, ml_df, local_silver_csv, local_ml_csv


# ─────────────────────────────────────────────
# Stage 5 — Push ML features to BigQuery
# ─────────────────────────────────────────────

def _ml_bq_stage(ml_df: pd.DataFrame) -> None:
    """
    Push the fraud-detection-ready feature table to BigQuery as ml_features.

    This is the ONLY table in BigQuery. It contains:
      - All numeric fraud-signal columns (financials, code counts, durations)
      - Safe categorical columns (claim_type, payer, outcome etc.)
      - secure_patient_id (hashed — no raw PHI)
      - No encrypted blobs, no raw PHI fields
    """
    print("\n" + "=" * 60)
    print("   Step 5 — ML Features  →  BigQuery (ml_features)")
    print("=" * 60)

    t0 = time.perf_counter()
    ml_df = ml_df.copy()

    for col in ["has_payment", "has_total_charge"]:
        if col in ml_df.columns:
            ml_df[col] = ml_df[col].astype(bool)

    numeric_cols = [
        "payment_amount", "total_charged", "total_line_items",
        "num_diagnosis_codes", "num_procedure_codes",
        "service_category_count", "modifier_count", "coverage_reference_count",
        "avg_payment_per_line", "avg_charge_per_line",
        "line_submitted_total", "line_eligible_total", "line_benefit_total",
        "line_paid_to_provider_total", "line_paid_to_patient_total",
        "line_deductible_total", "line_coinsurance_total",
        "line_priorpayer_total", "line_all_adjudication_total",
        "service_duration_days",
    ]
    for col in numeric_cols:
        if col in ml_df.columns:
            ml_df[col] = pd.to_numeric(ml_df[col], errors="coerce")

    print(f"  Rows    : {len(ml_df):,}")
    print(f"  Columns : {list(ml_df.columns)}")

    load_to_bigquery(ml_df, "ml_features")

    elapsed = round(time.perf_counter() - t0, 3)
    write_audit("ML_BQ_PUSH", f"SUCCESS - {len(ml_df)} rows -> ml_features in {elapsed}s")
    print(f"[ML BQ] {len(ml_df):,} rows pushed in {elapsed}s")


# ─────────────────────────────────────────────
# Stage 6 — Gold  (GCS only)
# ─────────────────────────────────────────────

def _gold_stage(silver_df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 60)
    print("   Step 6 — Gold  →  GCS only")
    print("=" * 60)

    t0 = time.perf_counter()
    gold_df = process_to_gold(silver_df)

    if not gold_df.empty:
        try:
            upload_gold_to_gcs(gold_df)
        except Exception as e:
            print(f"[WARN] Gold GCS upload failed: {e}")
            write_audit("GOLD_WARN", str(e))

    elapsed = round(time.perf_counter() - t0, 3)
    write_audit("GOLD_COMPLETE", f"SUCCESS - {len(gold_df)} rows in {elapsed}s")
    print(f"[Gold] {len(gold_df):,} rows in {elapsed}s")

    return gold_df


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def run_pipeline() -> None:
    pipeline_start = time.perf_counter()
    write_audit("PIPELINE_START", "STARTED")

    print("\n" + "=" * 60)
    print("   SecureHIC Pipeline")
    print("   Fetch → Bronze → Silver → ML(BQ) → Gold")
    print("=" * 60)

    combined_bundle, combined_path = _fetch_and_combine_stage()
    bronze = _bronze_stage(combined_bundle, benchmark_rounds=4)
    silver_df, ml_df, local_silver_csv, local_ml_csv = _silver_stage(combined_bundle)
    _ml_bq_stage(ml_df)
    gold_df = _gold_stage(silver_df)

    elapsed = round(time.perf_counter() - pipeline_start, 3)
    write_audit("PIPELINE_COMPLETE", f"SUCCESS in {elapsed}s")

    bronze_upload = bronze.get("upload", {})
    bronze_benchmark = bronze.get("benchmark", {})
    bench_summary = bronze_benchmark.get("summary", {})
    plot_paths = bronze_benchmark.get("plot_paths", {})

    print("\n" + "=" * 60)
    print(f"   Pipeline complete in {elapsed}s")
    print("=" * 60)
    print(f"   Combined bundle        : {combined_path}")
    print(f"   Local Silver CSV       : {local_silver_csv}")
    print(f"   Local ML CSV           : {local_ml_csv}")
    print(f"   Bronze raw (GCS)       : {bronze_upload.get('raw_path')}")
    print(f"   Bronze PQC (GCS)       : {bronze_upload.get('pqc_path')}")
    print(f"   Bronze Classical (GCS) : {bronze_upload.get('classical_path')}")
    print(f"   Benchmark raw JSON     : {bronze_benchmark.get('raw_path')}")
    print(f"   Benchmark summary JSON : {bronze_benchmark.get('summary_path')}")

    if bench_summary:
        print(f"   Avg classical enc      : {bench_summary.get('avg_classical_encrypt')}")
        print(f"   Avg PQC enc            : {bench_summary.get('avg_pqc_encrypt')}")
        print(f"   Avg classical dec      : {bench_summary.get('avg_classical_decrypt')}")
        print(f"   Avg PQC dec            : {bench_summary.get('avg_pqc_decrypt')}")
        print(f"   Avg sequential pipe    : {bench_summary.get('avg_sequential_pipeline')}")
        print(f"   Avg parallel pipe      : {bench_summary.get('avg_parallel_pipeline')}")
        print(f"   Speedup                : {bench_summary.get('speedup')}")

    if plot_paths:
        print(f"   Crypto plot            : {plot_paths.get('crypto_plot')}")
        print(f"   Decrypt plot           : {plot_paths.get('decrypt_plot')}")
        print(f"   Size plot              : {plot_paths.get('size_plot')}")
        print(f"   Speedup plot           : {plot_paths.get('speedup_plot')}")
        print(f"   Scalability plot       : {plot_paths.get('scalability_plot')}")
        print(f"   Pipeline plot          : {plot_paths.get('pipeline_plot')}")

    print(f"   Silver records         : {len(silver_df):,}")
    print(f"   BQ ml_features         : {len(ml_df):,} rows  →  {BQ_PROJECT}.{BQ_DATASET}.ml_features")
    print(f"   Gold rows (GCS)        : {len(gold_df):,}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_pipeline()