import sys
import os# Add src folder to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))



from config import CLIENT_ID, PATIENT_HASH_SALT



print(f"✅ Client ID loaded: {CLIENT_ID[:6]}...")  # only shows first 6 chars
print(f"✅ Salt loaded: {PATIENT_HASH_SALT[:6]}...")