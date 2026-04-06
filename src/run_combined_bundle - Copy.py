

import json
import pandas as pd

from silver import process_to_silver
from fhir_parser import anonymize_patient_id, make_ml_features


COMBINED_PATH = r"D:\SecureHIC\data\cms_fhir_bundle_combined.json"
OUT_SILVER = r"D:\SecureHIC\data\cms_fhir_silver_combined.csv"
OUT_ML = r"D:\SecureHIC\data\cms_fhir_ml_combined.csv"


def main():
    with open(COMBINED_PATH, "r", encoding="utf-8") as f:
        raw_bundle = json.load(f)

    print(f"[Load] Combined bundle entries: {len(raw_bundle.get('entry', []))}")

    silver_df = process_to_silver(raw_bundle, max_workers=4)
    silver_df = anonymize_patient_id(silver_df)
    ml_df = make_ml_features(silver_df)

    # Make Silver CSV readable
    silver_copy = silver_df.copy()
    for col in silver_copy.columns:
        silver_copy[col] = silver_copy[col].apply(
            lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x
        )

    silver_copy.to_csv(OUT_SILVER, index=False)
    ml_df.to_csv(OUT_ML, index=False)

    print(f"[OK] Secure Silver rows: {len(silver_df)}")
    print(f"[OK] ML rows: {len(ml_df)}")
    print(f"[OK] Silver CSV: {OUT_SILVER}")
    print(f"[OK] ML CSV: {OUT_ML}")


if __name__ == "__main__":
    main()