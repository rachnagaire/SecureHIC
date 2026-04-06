import requests
import pandas as pd

API_URL = "https://sandbox.bluebutton.cms.gov/v2/fhir/ExplanationOfBenefit"

TOKEN = "YOUR_ACCESS_TOKEN"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/fhir+json"
}

response = requests.get(API_URL, headers=headers)

data = response.json()

print("API Connected Successfully")