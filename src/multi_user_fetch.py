"""
multi_user_fetch.py
Fetch FHIR bundles for multiple CMS Blue Button sandbox users,
save each bundle locally, then combine them into one large bundle.

Fixes applied:
  - Removed input("Press Enter...") — no manual pause between users
  - Auth state (auth_code_holder) is now passed per-call, not a shared global
    This prevents state corruption if the flow is ever extended to parallel use
  - Browser opens, OAuth completes, next user starts automatically
  - Failed users are skipped with a warning instead of crashing the whole run
"""

import os
import json
from datetime import datetime

from api_client import fetch_full_fhir_bundle, get_oauth_token


TOP_USERS = [
    ("BBUser09338", "PW09338!"),
    ("BBUser02239", "PW02239!"),
    ("BBUser02950", "PW02950!"),
    ("BBUser01581", "PW01581!"),
]


def local_data_dir() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def save_bundle(bundle: dict, username: str) -> str:
    data_dir = local_data_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(data_dir, f"cms_fhir_bundle_{username}_{ts}.json")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)

    print(f"[OK] Saved bundle for {username}: {path}")
    return path


def combine_saved_bundles(
    file_paths: list[str],
    output_name: str = "cms_fhir_bundle_combined.json",
) -> str:
    all_entries = []

    for path in file_paths:
        with open(path, "r", encoding="utf-8") as f:
            bundle = json.load(f)

        entries = bundle.get("entry", [])
        print(f"[Combine] {os.path.basename(path)} -> {len(entries)} entries")
        all_entries.extend(entries)

    combined = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(all_entries),
        "entry": all_entries,
    }

    output_path = os.path.join(local_data_dir(), output_name)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

    print(f"[OK] Combined bundle saved: {output_path}")
    print(f"[OK] Total combined entries: {len(all_entries)}")
    return output_path


def run_multi_user_fetch():
    saved_files = []
    failed_users = []

    for idx, (username, password) in enumerate(TOP_USERS, start=1):
        print("\n" + "=" * 70)
        print(f"[User {idx}/{len(TOP_USERS)}] {username}")
        print("=" * 70)
        print("A browser window will open — log in and approve access.")
        print(f"  Username : {username}")
        print(f"  Password : {password}")

        try:
            # Each call to get_oauth_token() clears auth_code_holder internally
            # and opens its own browser + local callback server — no state leaks
            token = get_oauth_token(username_hint=username, password_hint=password)
            bundle = fetch_full_fhir_bundle(token)

            entry_count = len(bundle.get("entry", []))
            print(f"[OK] Retrieved {entry_count} entries for {username}")

            saved_path = save_bundle(bundle, username)
            saved_files.append(saved_path)

        except Exception as e:
            print(f"[WARN] Failed to fetch bundle for {username}: {e}")
            failed_users.append((username, str(e)))
            # Continue to the next user without stopping the whole run

    if not saved_files:
        raise RuntimeError("No bundles were successfully fetched — cannot combine.")

    combined_path = combine_saved_bundles(saved_files)

    print("\n" + "=" * 70)
    print(f"✅ Done. Combined bundle ready at:\n{combined_path}")
    print(f"   Successful users : {len(saved_files)}/{len(TOP_USERS)}")

    if failed_users:
        print(f"   Failed users     : {len(failed_users)}")
        for username, reason in failed_users:
            print(f"     - {username}: {reason}")

    print("=" * 70)


if __name__ == "__main__":
    run_multi_user_fetch()