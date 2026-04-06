import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from api_client import get_oauth_token

token = get_oauth_token()
print(f"✅ Token received: {token[:20]}...")