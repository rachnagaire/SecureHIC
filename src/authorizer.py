import urllib.parse
import webbrowser
import secrets
from verifypkce import code_verifier, code_challenge

from config import CLIENT_ID, REDIRECT_URI

STATE = secrets.token_urlsafe(16)
SCOPE = "openid profile patient/ExplanationOfBenefit.rs"
REDIRECT_URI = "http://localhost:8000/callback"

params = {
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "response_type": "code",
    "scope": SCOPE,
    "state": STATE,
    "code_challenge": code_challenge,
    "code_challenge_method": "S256"
}

authorize_url = "https://sandbox.bluebutton.cms.gov/v2/o/authorize/?" + urllib.parse.urlencode(params)
print("Authorization URL:", authorize_url)