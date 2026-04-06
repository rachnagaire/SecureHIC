import time
import pandas as pd
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

results = []

# ------------------------
# RSA Benchmark
# ------------------------

start = time.time()

private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048
)

public_key = private_key.public_key()

message = b"SecureHIC Healthcare Data"

ciphertext = public_key.encrypt(
    message,
    padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None
    )
)

end = time.time()

results.append({
    "Algorithm": "RSA-2048 Encryption",
    "Execution Time (ms)": (end-start)*1000
})

# ------------------------
# ECDSA Benchmark
# ------------------------

start = time.time()

private_key = ec.generate_private_key(ec.SECP256R1())

signature = private_key.sign(
    message,
    ec.ECDSA(hashes.SHA256())
)

end = time.time()

results.append({
    "Algorithm": "ECDSA Signature",
    "Execution Time (ms)": (end-start)*1000
})

# ------------------------
# SHA256 Benchmark
# ------------------------

start = time.time()

digest = hashes.Hash(hashes.SHA256())
digest.update(message)
digest.finalize()

end = time.time()

results.append({
    "Algorithm": "SHA-256 Hash",
    "Execution Time (ms)": (end-start)*1000
})

df = pd.DataFrame(results)

print("\nClassical Crypto Benchmark\n")
print(df)