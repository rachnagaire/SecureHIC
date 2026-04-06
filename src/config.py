import os
import secrets
import functools

# ── Load .env file if present (development fallback) ──────────
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass


# ─────────────────────────────────────────────
# GCP Project
# ─────────────────────────────────────────────
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "securehic")


# ─────────────────────────────────────────────
# Secret Manager — with local .env fallback
# ─────────────────────────────────────────────
@functools.lru_cache(maxsize=None)
def get_secret(secret_id: str) -> str:
    # ── Try GCP Secret Manager ────────────────
    try:
        from google.cloud import secretmanager
        client   = secretmanager.SecretManagerServiceClient()
        name     = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        value    = response.payload.data.decode("UTF-8").strip()
        print(f"[config] '{secret_id}' loaded from GCP Secret Manager")
        return value
    except Exception:
        pass

    # ── Fallback: .env / environment variable ─
    env_var = secret_id.upper().replace("-", "_")
    value   = os.environ.get(env_var)
    if value:
        print(f"[config] '{secret_id}' loaded from local env ({env_var})")
        return value

    raise RuntimeError(
        f"\n[config] Could not load secret '{secret_id}'."
        f"\n  Add to D:\\SecureHIC\\.env:  {env_var}=your_value_here"
    )


# ─────────────────────────────────────────────
# Lazy Secret
# Behaves exactly like a plain string in every
# context — requests, urlencode, format strings,
# dict values, comparisons, etc.
# ─────────────────────────────────────────────
class _LazySecret(str):
    """
    Subclasses str so it IS a string — no casting needed anywhere.
    The actual secret is fetched once on first use and cached.
    """
    def __new__(cls, secret_id: str):
        # Create a str instance with empty value for now
        instance = super().__new__(cls, "")
        instance._secret_id = secret_id
        instance._resolved  = False
        return instance

    def _resolve(self) -> str:
        """Fetch the real value and return it as a plain str."""
        return get_secret(self._secret_id)

    # ── Override every str method to resolve first ─────────────
    def __str__(self):        return self._resolve()
    def __repr__(self):       return repr(self._resolve())
    def __len__(self):        return len(self._resolve())
    def __iter__(self):       return iter(self._resolve())
    def __contains__(self, o):return o in self._resolve()
    def __add__(self, o):     return self._resolve() + o
    def __radd__(self, o):    return o + self._resolve()
    def __eq__(self, o):      return self._resolve() == o
    def __hash__(self):       return hash(self._resolve())
    def __getitem__(self, k): return self._resolve()[k]
    def __format__(self, s):  return format(self._resolve(), s)

    def encode(self, *a, **k):  return self._resolve().encode(*a, **k)
    def strip(self, *a):        return self._resolve().strip(*a)
    def split(self, *a, **k):   return self._resolve().split(*a, **k)
    def upper(self):            return self._resolve().upper()
    def lower(self):            return self._resolve().lower()
    def replace(self, *a, **k): return self._resolve().replace(*a, **k)
    def startswith(self, *a):   return self._resolve().startswith(*a)
    def endswith(self, *a):     return self._resolve().endswith(*a)


# ─────────────────────────────────────────────
# OAuth Credentials  (lazy — safe at import)
# ─────────────────────────────────────────────
CLIENT_ID     = _LazySecret("bluebutton-client-id")
CLIENT_SECRET = _LazySecret("bluebutton-client-secret")
REDIRECT_URI  = "http://127.0.0.1:8000/callback"

# ─────────────────────────────────────────────
# OAuth Flow Config
# ─────────────────────────────────────────────
OAUTH_STATE  = secrets.token_hex(16)
OAUTH_SCOPES = "patient/Patient.read patient/ExplanationOfBenefit.read patient/Coverage.read"

# ─────────────────────────────────────────────
# Google Cloud Storage
# ─────────────────────────────────────────────
GCS_BUCKET      = "securehic-medicaid-data"
GCS_BRONZE_PATH = "bronze/api_claims_data.csv"

# ─────────────────────────────────────────────
# BigQuery
# ─────────────────────────────────────────────
BQ_PROJECT = "securehic"
BQ_DATASET = "securehic_dataset"
BQ_TABLE   = "claims_raw"

# ─────────────────────────────────────────────
# Patient Hashing Salt  (lazy — safe at import)
# ─────────────────────────────────────────────
PATIENT_HASH_SALT = _LazySecret("patient-hash-salt")

# ─────────────────────────────────────────────
# Audit Logging
# ─────────────────────────────────────────────
AUDIT_LOG_PATH = "logs/audit.log"
os.makedirs("logs", exist_ok=True)