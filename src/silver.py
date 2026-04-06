"""
silver.py
SecureHIC — Silver layer claim processing

Updated to use the centralized FHIR parser instead of manually extracting
a limited subset of fields from raw entries.

Why this version:
- Works with CMS Blue Button ExplanationOfBenefit bundles
- Reuses split_fhir_bundle() and parse_fhir_to_df()
- Keeps Silver layer consistent with Bronze security design
- Still provides sequential vs parallel comparison for presentation/demo
"""

import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

from fhir_parser import split_fhir_bundle, parse_fhir_to_df


def _parse_bundle(raw_bundle: dict) -> pd.DataFrame:
    """
    Shared parser path:
      raw bundle -> split grouped resources -> parsed secure dataframe
    """
    fhir_data = split_fhir_bundle(raw_bundle)
    df = parse_fhir_to_df(fhir_data)
    return df


def process_bundle_sequential(raw_bundle: dict) -> tuple[pd.DataFrame, float]:
    """
    Sequential Silver processing.
    Useful for comparison against parallel processing.
    """
    t0 = time.perf_counter()
    df = _parse_bundle(raw_bundle)
    elapsed = time.perf_counter() - t0

    if "claim_id" in df.columns:
        df = df.sort_values(by="claim_id", na_position="last").reset_index(drop=True)

    print(f"[Sequential] Silver parsing completed in {elapsed:.6f}s")
    return df, elapsed


def process_bundle_parallel(raw_bundle: dict, max_workers: int = 4) -> tuple[pd.DataFrame, float]:
    """
    Parallel Silver processing.

    The raw bundle is split once, then the three resource groups are parsed
    in parallel:
      - EOB
      - Patient
      - Coverage

    After that, results are joined the same way as parse_fhir_to_df().
    """
    from fhir_parser import parse_eob, parse_patient, parse_coverage

    t0 = time.perf_counter()

    fhir_data = split_fhir_bundle(raw_bundle)
    eob_entries = fhir_data.get("eob", {}).get("entry", [])
    patient_entries = fhir_data.get("patient", {}).get("entry", [])
    coverage_entries = fhir_data.get("coverage", {}).get("entry", [])

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_eob = ex.submit(parse_eob, eob_entries)
        future_patient = ex.submit(parse_patient, patient_entries)
        future_coverage = ex.submit(parse_coverage, coverage_entries)

        eob_df = future_eob.result()
        patient_df = future_patient.result()
        coverage_df = future_coverage.result()

    if eob_df.empty:
        raise ValueError("No ExplanationOfBenefit rows found in Silver processing")

    df = eob_df.merge(patient_df, on="patient_reference", how="left")
    df = df.merge(coverage_df, on="patient_reference", how="left")

    if "claim_id" in df.columns:
        df = df.sort_values(by="claim_id", na_position="last").reset_index(drop=True)

    elapsed = time.perf_counter() - t0
    print(f"[Parallel] Silver parsing completed in {elapsed:.6f}s")
    return df, elapsed


def compare_sequential_vs_parallel(raw_bundle: dict, max_workers: int = 4) -> dict:
    """
    Compare sequential and parallel Silver processing.

    Returns timing, speedup, and whether outputs match structurally.
    """
    seq_df, seq_time = process_bundle_sequential(raw_bundle)
    par_df, par_time = process_bundle_parallel(raw_bundle, max_workers=max_workers)

    if "claim_id" in seq_df.columns:
        seq_df = seq_df.sort_values(by="claim_id", na_position="last").reset_index(drop=True)
    if "claim_id" in par_df.columns:
        par_df = par_df.sort_values(by="claim_id", na_position="last").reset_index(drop=True)

    same_shape = seq_df.shape == par_df.shape
    same_columns = list(seq_df.columns) == list(par_df.columns)
    speedup = round(seq_time / par_time, 2) if par_time > 0 else None

    print(f"[Compare] Sequential time : {seq_time:.6f}s")
    print(f"[Compare] Parallel time   : {par_time:.6f}s")
    print(f"[Compare] Speedup         : {speedup}x")
    print(f"[Compare] Same shape      : {same_shape}")
    print(f"[Compare] Same columns    : {same_columns}")

    return {
        "sequential_df": seq_df,
        "parallel_df": par_df,
        "sequential_time": round(seq_time, 6),
        "parallel_time": round(par_time, 6),
        "speedup": speedup,
        "same_shape": same_shape,
        "same_columns": same_columns,
    }


def process_to_silver(raw_bundle: dict, max_workers: int = 4) -> pd.DataFrame:
    """
    Main Silver entrypoint used by pipeline.py.

    Uses the parallel parser path by default.
    """
    silver_df, parallel_time = process_bundle_parallel(
        raw_bundle,
        max_workers=max_workers
    )
    print(f"[Silver] Parallel Silver processing completed in {parallel_time:.6f}s")
    return silver_df