import requests
import webbrowser
import hashlib
import base64
import secrets
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI
from audit import write_audit


# ─────────────────────────────────────────────
# CMS Blue Button Endpoints
# ─────────────────────────────────────────────
AUTH_URL = "https://sandbox.bluebutton.cms.gov/v2/o/authorize/"
TOKEN_URL = "https://sandbox.bluebutton.cms.gov/v2/o/token/"
FHIR_BASE_URL = "https://sandbox.bluebutton.cms.gov/v2/fhir"
FHIR_PATIENT_URL = f"{FHIR_BASE_URL}/Patient"
FHIR_EOB_URL = f"{FHIR_BASE_URL}/ExplanationOfBenefit"
FHIR_COVERAGE_URL = f"{FHIR_BASE_URL}/Coverage"

auth_code_holder = {}


# ─────────────────────────────────────────────
# PKCE Helpers
# ─────────────────────────────────────────────
def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")


# ─────────────────────────────────────────────
# Callback Handler
# ─────────────────────────────────────────────
class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        print(f"\n📥 Callback received: {self.path}")
        print(f"📋 Params: {params}")

        if "code" in params:
            auth_code_holder["code"] = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Success! You can close this tab.")

        elif "error" in params:
            error = params.get("error", ["unknown"])[0]
            error_desc = params.get("error_description", ["no description"])[0]
            print(f"\n❌ CMS error: {error} - {error_desc}")
            auth_code_holder["error"] = error
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Error: {error} - {error_desc}".encode("utf-8"))

        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code parameter.")

    def log_message(self, format, *args):
        pass


# ─────────────────────────────────────────────
# Common Request Helper
# ─────────────────────────────────────────────
def _auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/fhir+json",
    }


def _fetch_paginated_bundle(token: str, initial_url: str, pause_seconds: float = 0.2) -> dict:
    """
    Fetch all pages of a paginated FHIR bundle and combine into one bundle.
    """
    headers = _auth_headers(token)

    all_entries = []
    first_bundle = None
    next_url = initial_url
    page_num = 0

    while next_url:
        page_num += 1
        print(f"\n📦 Fetching page {page_num}")
        print(f"🔍 URL: {next_url}")

        response = requests.get(next_url, headers=headers, timeout=60)

        print(f"🔍 Status: {response.status_code}")
        print(f"🔍 Response preview: {response.text[:300]}")

        if response.status_code != 200:
            write_audit("FETCH_FHIR_PAGE", f"FAIL - {response.status_code}")
            raise Exception(
                f"❌ FHIR page fetch failed: {response.status_code} - {response.text}"
            )

        bundle = response.json()

        if first_bundle is None:
            first_bundle = bundle

        entries = bundle.get("entry", [])
        all_entries.extend(entries)
        print(f"✅ Page {page_num}: {len(entries)} records "
              f"(running total={len(all_entries)})")

        next_url = None
        for link in bundle.get("link", []):
            if link.get("relation") == "next":
                next_url = link.get("url")
                break

        if next_url:
            time.sleep(pause_seconds)

    combined_bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(all_entries),
        "entry": all_entries,
        "meta": first_bundle.get("meta", {}) if first_bundle else {},
        "link": first_bundle.get("link", []) if first_bundle else [],
    }

    return combined_bundle


# ─────────────────────────────────────────────
# Get OAuth Token
# ─────────────────────────────────────────────
def get_oauth_token(username_hint: str = "BBUser00000", password_hint: str = "PW00000!") -> str:
    """
    Open browser, perform Blue Button OAuth flow, exchange auth code for access token.
    """
    auth_code_holder.clear()

    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = secrets.token_hex(16)

    params = urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "profile patient/Patient.read patient/ExplanationOfBenefit.read patient/Coverage.read",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })

    auth_url = f"{AUTH_URL}?{params}"
    webbrowser.open(auth_url)

    print("🔐 Browser opened — log in with CMS sandbox credentials...")
    print(f"   Username: {username_hint}")
    print(f"   Password: {password_hint}")
    print("⏳ Waiting for callback on 127.0.0.1:8000...")

    server = HTTPServer(("127.0.0.1", 8000), CallbackHandler)
    server.handle_request()

    code = auth_code_holder.get("code")
    error = auth_code_holder.get("error")

    if error:
        write_audit("FETCH_TOKEN", f"FAIL - {error}")
        raise Exception(f"❌ CMS returned error: {error}")

    if not code:
        write_audit("FETCH_TOKEN", "FAIL - no authorization code")
        raise Exception("❌ No authorization code received")

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code_verifier": code_verifier,
        },
        timeout=60,
    )

    data = response.json()
    token = data.get("access_token")

    if not token:
        write_audit("FETCH_TOKEN", f"FAIL - token exchange failed: {data}")
        raise Exception(f"❌ Token exchange failed: {data}")

    write_audit("FETCH_TOKEN", "SUCCESS")
    print("✅ Token received!")
    return token
# ─────────────────────────────────────────────
# Fetch Patient
# ─────────────────────────────────────────────
def fetch_patient_bundle(token: str) -> dict:
    """
    Fetch the authenticated beneficiary's Patient bundle.
    """
    headers = _auth_headers(token)

    print(f"\n🔍 Fetching Patient: {FHIR_PATIENT_URL}")
    response = requests.get(FHIR_PATIENT_URL, headers=headers, timeout=60)

    print(f"🔍 Status: {response.status_code}")
    print(f"🔍 Response preview: {response.text[:300]}")

    if response.status_code != 200:
        write_audit("FETCH_PATIENT", "FAIL")
        raise Exception(f"❌ Patient fetch failed: {response.status_code} - {response.text}")

    bundle = response.json()
    write_audit("FETCH_PATIENT", "SUCCESS")
    print("✅ Patient bundle fetched!")
    return bundle


def get_patient_id(token: str) -> str:
    """
    Read patient id from authenticated /Patient bundle.
    """
    bundle = fetch_patient_bundle(token)
    entries = bundle.get("entry", [])

    if not entries:
        write_audit("GET_PATIENT_ID", "FAIL - no patient entries")
        raise Exception("❌ No patient entry returned from /Patient")

    patient_id = entries[0].get("resource", {}).get("id")
    if not patient_id:
        write_audit("GET_PATIENT_ID", "FAIL - missing patient id")
        raise Exception("❌ Patient ID missing from /Patient response")

    write_audit("GET_PATIENT_ID", f"SUCCESS - {patient_id}")
    print(f"✅ Patient ID: {patient_id}")
    return patient_id


# ─────────────────────────────────────────────
# Fetch FHIR Claims
# ─────────────────────────────────────────────
def fetch_fhir_claims(token: str, count: int = 50) -> dict:
    """
    Fetch all ExplanationOfBenefit pages for the authenticated patient.
    """
    patient_id = get_patient_id(token)

    initial_url = (
        f"{FHIR_EOB_URL}"
        f"?patient={patient_id}"
        f"&_count={count}"
        f"&_format=application/fhir+json"
    )

    print(f"\n🔍 Starting EOB fetch for patient: {patient_id}")

    bundle = _fetch_paginated_bundle(token, initial_url)
    write_audit("FETCH_FHIR_CLAIMS", f"SUCCESS - {len(bundle.get('entry', []))} EOB records")
    print(f"✅ FHIR claims fetched! Total EOB records: {len(bundle.get('entry', []))}")
    return bundle


# ─────────────────────────────────────────────
# Fetch Coverage
# ─────────────────────────────────────────────
def fetch_fhir_coverage(token: str, count: int = 50) -> dict:
    """
    Fetch all Coverage pages for the authenticated patient.
    """
    patient_id = get_patient_id(token)

    initial_url = (
        f"{FHIR_COVERAGE_URL}"
        f"?beneficiary={patient_id}"
        f"&_count={count}"
        f"&_format=application/fhir+json"
    )

    print(f"\n🔍 Starting Coverage fetch for patient: {patient_id}")

    bundle = _fetch_paginated_bundle(token, initial_url)
    write_audit("FETCH_FHIR_COVERAGE", f"SUCCESS - {len(bundle.get('entry', []))} Coverage records")
    print(f"✅ Coverage fetched! Total Coverage records: {len(bundle.get('entry', []))}")
    return bundle


# ─────────────────────────────────────────────
# Combined Patient + Coverage + EOB Bundle
# ─────────────────────────────────────────────
def fetch_full_fhir_bundle(token: str, count: int = 50) -> dict:
    """
    Fetch Patient, Coverage, and ExplanationOfBenefit and combine into one bundle.
    This is useful if your downstream parser expects multiple resource types.
    """
    patient_bundle = fetch_patient_bundle(token)
    coverage_bundle = fetch_fhir_coverage(token, count=count)
    eob_bundle = fetch_fhir_claims(token, count=count)

    all_entries = []
    all_entries.extend(patient_bundle.get("entry", []))
    all_entries.extend(coverage_bundle.get("entry", []))
    all_entries.extend(eob_bundle.get("entry", []))

    combined = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(all_entries),
        "entry": all_entries,
    }

    write_audit("FETCH_FULL_FHIR_BUNDLE", f"SUCCESS - {len(all_entries)} combined entries")
    print(f"✅ Full FHIR bundle created! Total combined entries: {len(all_entries)}")
    return combined