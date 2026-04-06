"""
cloud_upload.py
SecureHIC — GCS + BigQuery Upload Layer

Bronze : Raw FHIR + PQC encrypted + Classical encrypted
Silver : Normalized claims -> GCS + BigQuery
Gold   : Aggregated analytics -> GCS + BigQuery

Fix: Added SafeJSONEncoder to handle Python date, datetime, Decimal,
     and float NaN/Inf values that pandas produces and json.dumps chokes on.
"""

import json
import math
import pandas as pd
from datetime import date, datetime, timezone
from decimal import Decimal

from google.cloud import storage, bigquery
from google.api_core.exceptions import GoogleAPIError, NotFound

from config import GCS_BUCKET, BQ_PROJECT, BQ_DATASET, BQ_TABLE
from audit import write_audit
from security import benchmark_encryption


# ─────────────────────────────────────────────
# Safe JSON Encoder
# ─────────────────────────────────────────────

class SafeJSONEncoder(json.JSONEncoder):
    """
    Handles types that pandas produces but json.dumps can't serialize:
      - datetime.date  -> "YYYY-MM-DD"
      - datetime.datetime -> ISO 8601 string
      - decimal.Decimal -> float
      - float NaN / Inf -> None  (JSON has no NaN)
    """
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

    def iterencode(self, obj, _one_shot=False):
        # Intercept float NaN/Inf before they hit the C encoder
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            yield "null"
            return
        yield from super().iterencode(obj, _one_shot)


def _safe_json_dumps(data, indent=2) -> bytes:
    return json.dumps(data, indent=indent, cls=SafeJSONEncoder).encode("utf-8")


def _records_from_df(df: pd.DataFrame) -> list:
    """
    Convert DataFrame to records, replacing NaN/NaT with None
    so SafeJSONEncoder sees clean Python types.
    """
    return df.where(pd.notnull(df), other=None).to_dict(orient="records")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _ts():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _upload_json(bucket, path: str, data, label: str):
    content = _safe_json_dumps(data) if not isinstance(data, bytes) else data
    bucket.blob(path).upload_from_string(content, content_type="application/json")
    print(f"[OK] {label} -> gs://{GCS_BUCKET}/{path}")


def _flatten_for_bq(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, (dict, list))).any():
            df[col] = df[col].apply(
                lambda x: json.dumps(x, cls=SafeJSONEncoder)
                if isinstance(x, (dict, list)) else x
            )
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).replace("None", "").replace("nan", "")
    return df


def _ensure_dataset(client: bigquery.Client):
    dataset_id = f"{BQ_PROJECT}.{BQ_DATASET}"
    try:
        client.get_dataset(dataset_id)
    except NotFound:
        ds = bigquery.Dataset(dataset_id)
        ds.location = "US"
        client.create_dataset(ds)
        print(f"[OK] BigQuery dataset created: {dataset_id}")


# ─────────────────────────────────────────────
# Bronze
# ─────────────────────────────────────────────

def upload_raw_to_bronze(fhir_data: dict):
    """
    Upload Bronze artefacts to GCS.
    Returns dict with raw_path, pqc_path, classical_path.
    """
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        ts = _ts()
        raw_json = _safe_json_dumps(fhir_data)

        raw_path = f"bronze/raw/raw_fhir_{ts}.json"
        _upload_json(bucket, raw_path, fhir_data, "Bronze raw FHIR")

        results = benchmark_encryption(raw_json)

        pqc_path = f"bronze/pqc_encrypted/fhir_{ts}.kyber.json"
        _upload_json(bucket, pqc_path, results["pqc"], "Bronze PQC encrypted")

        cls_path = f"bronze/classical_encrypted/fhir_{ts}.rsa.json"
        _upload_json(bucket, cls_path, results["classical"], "Bronze Classical encrypted")

        record_count = len(fhir_data.get("entry", []))
        write_audit(
            "UPLOAD_RAW_BRONZE",
            f"SUCCESS - {record_count} entries | "
            f"PQC:{results['benchmark']['pqc_time_seconds']}s | "
            f"Classical:{results['benchmark']['classical_time_seconds']}s",
        )

        return {
            "raw_path": raw_path,
            "pqc_path": pqc_path,
            "classical_path": cls_path,
        }

    except GoogleAPIError as e:
        write_audit("UPLOAD_RAW_BRONZE", f"FAIL - {e}")
        raise RuntimeError(f"[FAIL] Bronze upload failed: {e}")


# ─────────────────────────────────────────────
# Silver
# ─────────────────────────────────────────────

def upload_silver_to_gcs(df: pd.DataFrame):
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        ts = _ts()

        silver_json_path = f"silver/claims/silver_claims_{ts}.json"
        records = _records_from_df(df)
        _upload_json(bucket, silver_json_path, records, "Silver JSON")

        flat_df = _flatten_for_bq(df)
        silver_csv_path = f"silver/claims/silver_claims_{ts}.csv"
        bucket.blob(silver_csv_path).upload_from_string(
            flat_df.to_csv(index=False), content_type="text/csv"
        )
        print(f"[OK] Silver CSV -> gs://{GCS_BUCKET}/{silver_csv_path}")

        write_audit("UPLOAD_SILVER_GCS", f"SUCCESS - {len(df)} rows -> silver/claims/")

    except GoogleAPIError as e:
        write_audit("UPLOAD_SILVER_GCS", f"FAIL - {e}")
        raise RuntimeError(f"[FAIL] Silver GCS upload failed: {e}")


# ─────────────────────────────────────────────
# Gold
# ─────────────────────────────────────────────

def upload_gold_to_gcs(df: pd.DataFrame):
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        ts = _ts()

        gold_json_path = f"gold/aggregates/gold_claims_{ts}.json"
        records = _records_from_df(df)          # date objects come from here
        _upload_json(bucket, gold_json_path, records, "Gold JSON")

        gold_csv_path = f"gold/aggregates/gold_claims_{ts}.csv"
        bucket.blob(gold_csv_path).upload_from_string(
            df.to_csv(index=False), content_type="text/csv"
        )
        print(f"[OK] Gold CSV -> gs://{GCS_BUCKET}/{gold_csv_path}")

        write_audit("UPLOAD_GOLD_GCS", f"SUCCESS - {len(df)} rows -> gold/aggregates/")

    except GoogleAPIError as e:
        write_audit("UPLOAD_GOLD_GCS", f"FAIL - {e}")
        raise RuntimeError(f"[FAIL] Gold GCS upload failed: {e}")


# ─────────────────────────────────────────────
# BigQuery
# ─────────────────────────────────────────────

def load_to_bigquery(df: pd.DataFrame, table_name: str = None):
    try:
        client = bigquery.Client(project=BQ_PROJECT)
        _ensure_dataset(client)

        table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{table_name or BQ_TABLE}"
        flat_df = _flatten_for_bq(df)

        job = client.load_table_from_dataframe(
            flat_df,
            table_id,
            job_config=bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=True,
            ),
        )
        job.result()

        print(f"[OK] {len(df)} rows -> BigQuery {table_id}")
        write_audit("LOAD_TO_BIGQUERY", f"SUCCESS - {len(df)} rows -> {table_id}")

    except GoogleAPIError as e:
        write_audit("LOAD_TO_BIGQUERY", f"FAIL - {e}")
        raise RuntimeError(f"[FAIL] BigQuery load failed: {e}")