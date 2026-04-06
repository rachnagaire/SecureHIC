# tests/test_config.py
import sys
import os
import requests
from dotenv import load_dotenv

# -------------------------------
# Add src/ folder to Python path
# -------------------------------
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
sys.path.insert(0, SRC_PATH)

# Now import config
from config import CLIENT_ID, CLIENT_SECRET, GCS_BUCKET, PATIENT_HASH_SALT

# -------------------------------
# Load .env
# -------------------------------
load_dotenv()

print("CLIENT_ID:", CLIENT_ID)
print("CLIENT_SECRET:", CLIENT_SECRET)
print("GCS_BUCKET:", GCS_BUCKET)
print("PATIENT_HASH_SALT:", PATIENT_HASH_SALT)

if CLIENT_ID and CLIENT_SECRET:
    print("✅ Environment variables loaded correctly")
else:
    print("❌ Check your .env file or load_dotenv()")

# -------------------------------
# Optional: Test OAuth token fetch
# -------------------------------
TOKEN_URL = "https://sandbox.bluebutton.cms.gov/v2/o/token/"

try:
    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    response = requests.post(TOKEN_URL, data=payload)
    print("\nToken request status code:", response.status_code)
    print("Token response body:", response.text)
    
    token = response.json().get("access_token")
    if token:
        print(" Successfully received OAuth token")
    else:
        print(" Failed to get OAuth token. Check your credentials and sandbox environment")
except Exception as e:
    print(" Exception while fetching token:", e)