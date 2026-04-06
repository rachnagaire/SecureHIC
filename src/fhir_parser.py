"""
parser.py
──────────────────────────────────────────────────────────────────
FHIR Bundle Parser for SecureHIC Bronze Layer

Updated for CMS Blue Button ExplanationOfBenefit-centric bundles.

What this version does:
  - Parses ExplanationOfBenefit, Patient, and Coverage safely
  - Works even when Patient/Coverage entries are missing
  - Extracts richer EOB fields for downstream ML feature creation
  - Keeps PHI encrypted / hashed for Bronze layer security
  - Adds ML-friendly plain derived numeric features

PHI field classification:
  ENCRYPT : patient_name, patient_dob, patient_gender,
            diagnosis_codes, procedure_codes, provider, facility
  HASH    : patient_reference, patient_zip, patient_state,
            insurance_plan_id, group_id, claim_id
  PLAIN   : status, claim_type, service dates, amounts, outcomes,
            counts / derived numeric features
──────────────────────────────────────────────────────────────────
"""

import hashlib
import json
from typing import Any, Dict, List, Optional

import pandas as pd

from config import PATIENT_HASH_SALT
from audit import write_audit
from security import encrypt_with_kyber


# ─────────────────────────────────────────────
# PHI Field Classification
# ─────────────────────────────────────────────

PHI_ENCRYPT_FIELDS = {
    "patient_name",
    "patient_dob",
    "patient_gender",
    "diagnosis_codes",
    "procedure_codes",
    "provider",
    "facility",
}

PHI_HASH_FIELDS = {
    "patient_reference",
    "patient_zip",
    "patient_state",
    "insurance_plan_id",
    "group_id",
    "claim_id",
}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _encrypt_phi(value: Any) -> Optional[dict]:
    """
    Encrypt a PHI field value using Kyber512 + AES256GCM + Dilithium2.
    Serializes the value as JSON bytes to preserve Python types.
    """
    if value is None:
        return None
    raw = json.dumps(value).encode("utf-8")
    return encrypt_with_kyber(raw)


def _hash_phi(value: Any) -> Optional[str]:
    """
    One-way SHA3-512 hash with project salt.
    Used for stable joins / analytics-safe identifiers.
    """
    if value is None:
        return None
    return "sha3_512:" + hashlib.sha3_512(
        (str(value) + PATIENT_HASH_SALT).encode("utf-8")
    ).hexdigest()


def _safe_get_coding_code(obj: dict, path: List[str], default=None):
    """
    Convenience helper for nested coding[0].code style extraction.
    """
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _extract_first_amount_from_total(total_list: list) -> Optional[float]:
    """
    Extract the first amount value from EOB.total if present.
    """
    for item in total_list or []:
        amt = item.get("amount", {}).get("value")
        if amt is not None:
            return amt
    return None


def _extract_line_item_financials(items: list) -> Dict[str, float]:
    """
    Traverse item[].adjudication[] and aggregate common financial amounts.

    Returns totals for submitted, eligible, benefit, paid, deductible, etc.
    """
    result = {
        "line_submitted_total": 0.0,
        "line_eligible_total": 0.0,
        "line_benefit_total": 0.0,
        "line_paid_to_provider_total": 0.0,
        "line_paid_to_patient_total": 0.0,
        "line_deductible_total": 0.0,
        "line_coinsurance_total": 0.0,
        "line_priorpayer_total": 0.0,
        "line_all_adjudication_total": 0.0,
    }

    for item in items or []:
        for adj in item.get("adjudication", []):
            amount = adj.get("amount", {}).get("value")
            if amount is None:
                continue

            result["line_all_adjudication_total"] += float(amount)

            codes = [
                coding.get("code")
                for coding in adj.get("category", {}).get("coding", [])
                if coding.get("code")
            ]

            if "submitted" in codes:
                result["line_submitted_total"] += float(amount)
            if "eligible" in codes:
                result["line_eligible_total"] += float(amount)
            if "benefit" in codes:
                result["line_benefit_total"] += float(amount)
            if "paidtoprovider" in codes:
                result["line_paid_to_provider_total"] += float(amount)
            if "paidtopatient" in codes:
                result["line_paid_to_patient_total"] += float(amount)
            if "deductible" in codes:
                result["line_deductible_total"] += float(amount)
            if "coinsurance" in codes:
                result["line_coinsurance_total"] += float(amount)
            if "priorpayerpaid" in codes:
                result["line_priorpayer_total"] += float(amount)

    return result


def _extract_diagnosis_codes(eob: dict) -> List[str]:
    """
    Extract diagnosis codes from ExplanationOfBenefit.diagnosis.
    """
    codes: List[str] = []
    for diagnosis in eob.get("diagnosis", []):
        for coding in diagnosis.get("diagnosisCodeableConcept", {}).get("coding", []):
            code = coding.get("code")
            if code:
                codes.append(code)
    return codes


def _extract_procedure_codes(eob: dict) -> List[str]:
    """
    Extract procedure/service codes from EOB.

    CMS Blue Button EOBs commonly store service codes in item[].productOrService,
    not only in top-level procedure[].
    """
    codes: List[str] = []

    # Top-level procedure[]
    for procedure in eob.get("procedure", []):
        for coding in procedure.get("procedureCodeableConcept", {}).get("coding", []):
            code = coding.get("code")
            if code:
                codes.append(code)

    # Line-level productOrService
    for item in eob.get("item", []):
        for coding in item.get("productOrService", {}).get("coding", []):
            code = coding.get("code")
            if code:
                codes.append(code)

    return codes


def _extract_service_categories(eob: dict) -> List[str]:
    categories: List[str] = []
    for item in eob.get("item", []):
        for coding in item.get("category", {}).get("coding", []):
            code = coding.get("code")
            if code:
                categories.append(code)
    return categories


def _extract_modifiers(eob: dict) -> List[str]:
    modifiers: List[str] = []
    for item in eob.get("item", []):
        for mod in item.get("modifier", []):
            for coding in mod.get("coding", []):
                code = coding.get("code")
                if code:
                    modifiers.append(code)
    return modifiers


def _extract_provider_display(eob: dict) -> Optional[str]:
    provider = eob.get("provider", {})
    if provider.get("display"):
        return provider.get("display")

    identifier_value = provider.get("identifier", {}).get("value")
    if identifier_value:
        return str(identifier_value)

    for ct in eob.get("careTeam", []):
        display = ct.get("provider", {}).get("display")
        if display:
            return display

        identifier_value = ct.get("provider", {}).get("identifier", {}).get("value")
        if identifier_value:
            return str(identifier_value)

    return None


def _extract_facility_display(eob: dict) -> Optional[str]:
    facility = eob.get("facility", {})
    if facility.get("display"):
        return facility.get("display")

    identifier_value = facility.get("identifier", {}).get("value")
    if identifier_value:
        return str(identifier_value)

    return None


# ─────────────────────────────────────────────
# Bundle Splitter
# ─────────────────────────────────────────────

def split_fhir_bundle(bundle: dict) -> dict:
    """
    Split a raw FHIR Bundle into grouped resources expected by parse_fhir_to_df().

    Input:
        {"resourceType": "Bundle", "entry": [...]}

    Output:
        {
            "eob": {"entry": [...]},
            "patient": {"entry": [...]},
            "coverage": {"entry": [...]}
        }
    """
    grouped = {
        "eob": {"entry": []},
        "patient": {"entry": []},
        "coverage": {"entry": []},
    }

    resource_map = {
        "ExplanationOfBenefit": "eob",
        "Patient": "patient",
        "Coverage": "coverage",
    }

    for entry in bundle.get("entry", []):
        resource_type = entry.get("resource", {}).get("resourceType")
        key = resource_map.get(resource_type)
        if key:
            grouped[key]["entry"].append(entry)

    write_audit(
        "SPLIT_FHIR_BUNDLE",
        (
            f"SUCCESS - eob={len(grouped['eob']['entry'])} "
            f"patient={len(grouped['patient']['entry'])} "
            f"coverage={len(grouped['coverage']['entry'])} entries"
        ),
    )

    print(
        f"[OK] Bundle split — "
        f"EOB: {len(grouped['eob']['entry'])}, "
        f"Patient: {len(grouped['patient']['entry'])}, "
        f"Coverage: {len(grouped['coverage']['entry'])}"
    )

    return grouped


# ─────────────────────────────────────────────
# Resource Parsers
# ─────────────────────────────────────────────

def parse_patient(patient_entries: list) -> pd.DataFrame:
    """
    Parse Patient resources.

    Keeps PHI encrypted and quasi-identifiers hashed.
    Returns an empty DataFrame with expected columns if no entries exist.
    """
    columns = [
        "patient_reference",
        "patient_name",
        "patient_dob",
        "patient_gender",
        "patient_state",
        "patient_zip",
    ]

    if not patient_entries:
        return pd.DataFrame(columns=columns)

    records = []

    for entry in patient_entries:
        r = entry.get("resource", {})
        name = (r.get("name") or [{}])[0]
        addr = (r.get("address") or [{}])[0]

        family = name.get("family", "") or ""
        given = " ".join(name.get("given", []) or [])
        full_name = f"{family} {given}".strip()

        records.append(
            {
                "patient_reference": _hash_phi(f"Patient/{r.get('id')}"),
                "patient_name": _encrypt_phi(full_name if full_name else None),
                "patient_dob": _encrypt_phi(r.get("birthDate")),
                "patient_gender": _encrypt_phi(r.get("gender")),
                "patient_state": _hash_phi(addr.get("state")),
                "patient_zip": _hash_phi(addr.get("postalCode")),
            }
        )

    df = pd.DataFrame(records, columns=columns)
    write_audit("PARSE_PATIENT", f"SUCCESS - {len(df)} patient records secured")
    print(f"[OK] Parsed {len(df)} Patient records — PHI encrypted/hashed")
    return df


def parse_coverage(coverage_entries: list) -> pd.DataFrame:
    """
    Parse Coverage resources.

    Returns an empty DataFrame with expected columns if no entries exist.
    """
    columns = [
        "patient_reference",
        "insurance_plan_id",
        "group_id",
        "insurance_type",
        "insurance_status",
        "coverage_start",
        "coverage_end",
        "payer",
        "plan_name",
    ]

    if not coverage_entries:
        return pd.DataFrame(columns=columns)

    records = []

    for entry in coverage_entries:
        r = entry.get("resource", {})
        classes = r.get("class", []) or []

        group_value = classes[1].get("value") if len(classes) > 1 else None
        plan_name = classes[0].get("value") if len(classes) > 0 else None

        payors = r.get("payor", []) or [{}]
        payer_value = payors[0].get("identifier", {}).get("value")

        insurance_type = None
        type_obj = r.get("type", {})
        if type_obj.get("coding"):
            insurance_type = type_obj["coding"][0].get("code")

        records.append(
            {
                "patient_reference": _hash_phi(
                    r.get("beneficiary", {}).get("reference")
                ),
                "insurance_plan_id": _hash_phi(r.get("id")),
                "group_id": _hash_phi(group_value),
                "insurance_type": insurance_type,
                "insurance_status": r.get("status"),
                "coverage_start": r.get("period", {}).get("start"),
                "coverage_end": r.get("period", {}).get("end"),
                "payer": payer_value,
                "plan_name": plan_name,
            }
        )

    df = pd.DataFrame(records, columns=columns)
    write_audit("PARSE_COVERAGE", f"SUCCESS - {len(df)} coverage records")
    print(f"[OK] Parsed {len(df)} Coverage records")
    return df


def parse_eob(eob_entries: list) -> pd.DataFrame:
    """
    Parse ExplanationOfBenefit resources.

    Keeps sensitive fields encrypted / hashed for Bronze.
    Adds ML-friendly numeric features in plain form.
    """
    columns = [
        "claim_id",
        "patient_reference",
        "diagnosis_codes",
        "procedure_codes",
        "provider",
        "facility",
        "status",
        "claim_type",
        "payer",
        "insurance_type",
        "service_date_start",
        "service_date_end",
        "total_charged",
        "payment_amount",
        "total_line_items",
        "outcome",
        "num_diagnosis_codes",
        "num_procedure_codes",
        "service_category_count",
        "modifier_count",
        "coverage_reference_count",
        "avg_payment_per_line",
        "avg_charge_per_line",
        "has_payment",
        "has_total_charge",
        "line_submitted_total",
        "line_eligible_total",
        "line_benefit_total",
        "line_paid_to_provider_total",
        "line_paid_to_patient_total",
        "line_deductible_total",
        "line_coinsurance_total",
        "line_priorpayer_total",
        "line_all_adjudication_total",
    ]

    if not eob_entries:
        return pd.DataFrame(columns=columns)

    records = []

    for entry in eob_entries:
        r = entry.get("resource", {})
        items = r.get("item", []) or []

        diagnoses = _extract_diagnosis_codes(r)
        procedures = _extract_procedure_codes(r)
        service_categories = _extract_service_categories(r)
        modifiers = _extract_modifiers(r)

        provider_value = _extract_provider_display(r)
        facility_value = _extract_facility_display(r)

        payment_amount = r.get("payment", {}).get("amount", {}).get("value")
        total_charged = _extract_first_amount_from_total(r.get("total", []))

        line_financials = _extract_line_item_financials(items)

        if total_charged is None:
            # Best available fallback if total[] is absent
            if line_financials["line_submitted_total"] > 0:
                total_charged = line_financials["line_submitted_total"]
            elif line_financials["line_all_adjudication_total"] > 0:
                total_charged = line_financials["line_all_adjudication_total"]
            else:
                total_charged = 0.0

        total_line_items = len(items)

        avg_payment_per_line = (
            float(payment_amount) / total_line_items
            if payment_amount is not None and total_line_items > 0
            else None
        )

        avg_charge_per_line = (
            float(total_charged) / total_line_items
            if total_line_items > 0 and total_charged is not None
            else None
        )

        type_codings = r.get("type", {}).get("coding", []) or []
        claim_type = type_codings[0].get("code") if len(type_codings) > 0 else None
        insurance_type = claim_type

        payer = r.get("insurer", {}).get("identifier", {}).get("value")

        coverage_refs = [
            ins.get("coverage", {}).get("reference")
            for ins in r.get("insurance", [])
            if ins.get("coverage", {}).get("reference")
        ]

        records.append(
            {
                "claim_id": _hash_phi(r.get("id")),
                "patient_reference": _hash_phi(r.get("patient", {}).get("reference")),
                "diagnosis_codes": _encrypt_phi("|".join(sorted(set(filter(None, diagnoses))))),
                "procedure_codes": _encrypt_phi("|".join(sorted(set(filter(None, procedures))))),
                "provider": _encrypt_phi(provider_value),
                "facility": _encrypt_phi(facility_value),
                "status": r.get("status"),
                "claim_type": claim_type,
                "payer": payer,
                "insurance_type": insurance_type,
                "service_date_start": r.get("billablePeriod", {}).get("start"),
                "service_date_end": r.get("billablePeriod", {}).get("end"),
                "total_charged": total_charged,
                "payment_amount": payment_amount,
                "total_line_items": total_line_items,
                "outcome": r.get("outcome"),
                "num_diagnosis_codes": len(set(filter(None, diagnoses))),
                "num_procedure_codes": len(set(filter(None, procedures))),
                "service_category_count": len(set(filter(None, service_categories))),
                "modifier_count": len(set(filter(None, modifiers))),
                "coverage_reference_count": len(coverage_refs),
                "avg_payment_per_line": avg_payment_per_line,
                "avg_charge_per_line": avg_charge_per_line,
                "has_payment": payment_amount is not None,
                "has_total_charge": total_charged is not None,
                "line_submitted_total": line_financials["line_submitted_total"],
                "line_eligible_total": line_financials["line_eligible_total"],
                "line_benefit_total": line_financials["line_benefit_total"],
                "line_paid_to_provider_total": line_financials["line_paid_to_provider_total"],
                "line_paid_to_patient_total": line_financials["line_paid_to_patient_total"],
                "line_deductible_total": line_financials["line_deductible_total"],
                "line_coinsurance_total": line_financials["line_coinsurance_total"],
                "line_priorpayer_total": line_financials["line_priorpayer_total"],
                "line_all_adjudication_total": line_financials["line_all_adjudication_total"],
            }
        )

    df = pd.DataFrame(records, columns=columns)
    write_audit("PARSE_EOB", f"SUCCESS - {len(df)} EOB records — enriched for ML")
    print(f"[OK] Parsed {len(df)} EOB records — enriched for ML-ready features")
    return df


# ─────────────────────────────────────────────
# Main Parse + Join
# ─────────────────────────────────────────────

def parse_fhir_to_df(fhir_data: dict) -> pd.DataFrame:
    """
    Parse and join EOB + Patient + Coverage into one Bronze-ready DataFrame.

    This version tolerates bundles that contain only EOB resources.
    Joins always use hashed patient_reference.
    """
    required_keys = ["eob", "patient", "coverage"]
    missing = [k for k in required_keys if k not in fhir_data]
    if missing:
        raise KeyError(
            f"fhir_data is missing required keys: {missing}. "
            f"Got: {list(fhir_data.keys())}. "
            f"If passing a raw FHIR Bundle, call split_fhir_bundle() first."
        )

    eob_entries = fhir_data.get("eob", {}).get("entry", [])
    patient_entries = fhir_data.get("patient", {}).get("entry", [])
    coverage_entries = fhir_data.get("coverage", {}).get("entry", [])

    eob_df = parse_eob(eob_entries)
    patient_df = parse_patient(patient_entries)
    coverage_df = parse_coverage(coverage_entries)

    if eob_df.empty:
        write_audit("PARSE_FHIR_TO_DF", "FAIL - no EOB rows parsed")
        raise ValueError("No ExplanationOfBenefit rows found in FHIR data")

    df = eob_df.merge(patient_df, on="patient_reference", how="left")
    df = df.merge(coverage_df, on="patient_reference", how="left")

    if df.empty:
        write_audit("PARSE_FHIR_TO_DF", "FAIL - empty DataFrame after join")
        raise ValueError("Empty DataFrame after joining FHIR resources")

    write_audit(
        "PARSE_FHIR_TO_DF",
        f"SUCCESS - {len(df)} combined records — PHI secured at parse time",
    )
    print(
        f"[OK] Parsed and joined {len(df)} records "
        f"(EOB + Patient + Coverage when available) — all PHI secured"
    )
    return df


# ─────────────────────────────────────────────
# Backward Compatibility
# ─────────────────────────────────────────────

def anonymize_patient_id(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a stable analytics-safe secure_patient_id from the already-hashed
    patient_reference.

    PHI fields are already encrypted during parsing and are not dropped.
    """
    df = df.copy()
    df["secure_patient_id"] = df["patient_reference"]

    write_audit(
        "ANONYMIZE_PATIENT_ID",
        "SUCCESS - secure_patient_id added (PHI already encrypted at parse)",
    )
    print("[OK] secure_patient_id set from hashed patient_reference")
    return df


# ─────────────────────────────────────────────
# Optional ML-safe feature view
# ─────────────────────────────────────────────

def make_ml_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create a Silver/ML-friendly feature table from the secure Bronze dataframe.

    This does NOT decrypt PHI.
    It uses only plain numeric / categorical safe fields.
    """
    ml_df = df.copy()

    ml_df["service_date_start"] = pd.to_datetime(
        ml_df["service_date_start"], errors="coerce"
    )
    ml_df["service_date_end"] = pd.to_datetime(
        ml_df["service_date_end"], errors="coerce"
    )

    ml_df["service_duration_days"] = (
        ml_df["service_date_end"] - ml_df["service_date_start"]
    ).dt.days

    ml_df["service_duration_days"] = ml_df["service_duration_days"].fillna(0)

    safe_cols = [
        "secure_patient_id",
        "claim_type",
        "payer",
        "insurance_type",
        "insurance_status",
        "coverage_start",
        "coverage_end",
        "payment_amount",
        "total_charged",
        "total_line_items",
        "num_diagnosis_codes",
        "num_procedure_codes",
        "service_category_count",
        "modifier_count",
        "coverage_reference_count",
        "avg_payment_per_line",
        "avg_charge_per_line",
        "has_payment",
        "has_total_charge",
        "line_submitted_total",
        "line_eligible_total",
        "line_benefit_total",
        "line_paid_to_provider_total",
        "line_paid_to_patient_total",
        "line_deductible_total",
        "line_coinsurance_total",
        "line_priorpayer_total",
        "line_all_adjudication_total",
        "service_duration_days",
        "outcome",
    ]

    existing_cols = [col for col in safe_cols if col in ml_df.columns]
    return ml_df[existing_cols].copy()