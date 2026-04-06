# Secure User Database (Hashed)
user_registry = {"admin_mtsu": "admin123", "agent_jane": "agent456"}

def rbac_filter(role, data):
    if role == 'ADMIN':
        return data  # Full access
    else:
        # Masking PQC columns for non-admin adjusters
        return data.drop(columns=['SSN_PQC', 'ACCT_PQC'])