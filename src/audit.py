import datetime
from config import AUDIT_LOG_PATH

def write_audit(action, status):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(f"[{timestamp}] ACTION: {action} | STATUS: {status}\n")