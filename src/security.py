"""
security.py
──────────────────────────────────────────────────────────────
PQC + Classical encryption for SecureHIC
Algorithms:
  PQC       : Kyber512 (KEM) + AES-256-GCM + Dilithium2 (signature)
  Classical : RSA-4096 + AES-256-GCM
──────────────────────────────────────────────────────────────
"""

import os
import time
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

try:
    import oqs
  
    OQS_AVAILABLE = True
except ImportError:
    OQS_AVAILABLE = False
    print("[WARN] liboqs not available - using AES fallback")


# ─────────────────────────────────────────────
# Hashing (Anonymization)
# ─────────────────────────────────────────────
def pqc_hash(data: str, salt: str) -> str:
    return hashlib.sha3_512((str(data) + salt).encode()).hexdigest()


# ─────────────────────────────────────────────
# PQC Encryption — Kyber512 + AES-256-GCM + Dilithium2
# ─────────────────────────────────────────────
def encrypt_with_kyber(data: bytes) -> dict:
    start = time.perf_counter()

    if OQS_AVAILABLE:
        # ── Kyber512 KEM ──────────────────────────
        with oqs.KeyEncapsulation("Kyber512") as kem:
            public_key                = kem.generate_keypair()
            ciphertext, shared_secret = kem.encap_secret(public_key)
            private_key               = kem.export_secret_key()

        # ── AES-256-GCM data encryption ───────────
        nonce          = os.urandom(12)
        encrypted_data = AESGCM(shared_secret[:32]).encrypt(nonce, data, None)

        # ── Dilithium2 signature over ciphertext ──
        with oqs.Signature("Dilithium2") as signer:
            sig_public_key  = signer.generate_keypair()
            signature       = signer.sign(encrypted_data)
            sig_private_key = signer.export_secret_key()

        result = {
            "algorithm":       "Kyber512+AES256GCM+Dilithium2",
            "encrypted_data":  base64.b64encode(encrypted_data).decode(),
            "nonce":           base64.b64encode(nonce).decode(),
            "kem_ciphertext":  base64.b64encode(ciphertext).decode(),
            "kem_public_key":  base64.b64encode(public_key).decode(),
            "kem_private_key": base64.b64encode(private_key).decode(),
            "signature":       base64.b64encode(signature).decode(),
            "sig_public_key":  base64.b64encode(sig_public_key).decode(),
            "sig_private_key": base64.b64encode(sig_private_key).decode(),
        }

    else:
        # ── AES-256-GCM fallback ──────────────────
        key            = os.urandom(32)
        nonce          = os.urandom(12)
        encrypted_data = AESGCM(key).encrypt(nonce, data, None)

        result = {
            "algorithm":      "AES256GCM-fallback",
            "encrypted_data": base64.b64encode(encrypted_data).decode(),
            "nonce":          base64.b64encode(nonce).decode(),
            "key":            base64.b64encode(key).decode(),
        }

    elapsed = time.perf_counter() - start
    result["encryption_time_seconds"] = round(elapsed, 6)
    result["data_size_bytes"]         = len(data)
    return result


# ─────────────────────────────────────────────
# PQC Decryption
# ─────────────────────────────────────────────
def decrypt_with_kyber(enc: dict):
    start = time.perf_counter()

    if enc["algorithm"] == "AES256GCM-fallback":
        key       = base64.b64decode(enc["key"])
        nonce     = base64.b64decode(enc["nonce"])
        data      = base64.b64decode(enc["encrypted_data"])
        decrypted = AESGCM(key).decrypt(nonce, data, None)

    else:
        # ── Step 1: Verify Dilithium2 BEFORE decrypting ──────
        encrypted_data = base64.b64decode(enc["encrypted_data"])
        signature      = base64.b64decode(enc["signature"])
        sig_public_key = base64.b64decode(enc["sig_public_key"])
        sig_priv_bytes = base64.b64decode(enc["sig_private_key"])

        with oqs.Signature("Dilithium2") as verifier:
            verifier.secret_key = sig_priv_bytes
            is_valid = verifier.verify(encrypted_data, signature, sig_public_key)

        if not is_valid:
            raise ValueError("[FAIL] Dilithium2 verification failed — data may be tampered.")

        # ── Step 2: Kyber512 KEM decapsulation ───────────────
        ciphertext  = base64.b64decode(enc["kem_ciphertext"])
        private_key = base64.b64decode(enc["kem_private_key"])
        nonce       = base64.b64decode(enc["nonce"])

        with oqs.KeyEncapsulation("Kyber512", secret_key=private_key) as kem:
            shared_secret = kem.decap_secret(ciphertext)

        # ── Step 3: AES-256-GCM decrypt ──────────────────────
        decrypted = AESGCM(shared_secret[:32]).decrypt(nonce, encrypted_data, None)

    elapsed = time.perf_counter() - start
    return decrypted, elapsed


# ─────────────────────────────────────────────
# Classical Encryption — RSA-4096 + AES-256-GCM
# ─────────────────────────────────────────────
def encrypt_with_classical(data: bytes) -> dict:
    start      = time.perf_counter()
    rsa_key    = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    public_key = rsa_key.public_key()
    aes_key    = os.urandom(32)
    nonce      = os.urandom(12)

    encrypted_aes  = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    encrypted_data = AESGCM(aes_key).encrypt(nonce, data, None)
    private_pem    = rsa_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    elapsed = time.perf_counter() - start

    return {
        "algorithm":               "RSA4096+AES256GCM",
        "encrypted_data":          base64.b64encode(encrypted_data).decode(),
        "nonce":                   base64.b64encode(nonce).decode(),
        "encrypted_aes":           base64.b64encode(encrypted_aes).decode(),
        "private_key":             base64.b64encode(private_pem).decode(),
        "encryption_time_seconds": round(elapsed, 6),
        "data_size_bytes":         len(data),
    }


# ─────────────────────────────────────────────
# Classical Decryption
# ─────────────────────────────────────────────
def decrypt_with_classical(enc: dict):
    start       = time.perf_counter()
    private_key = serialization.load_pem_private_key(
        base64.b64decode(enc["private_key"]), password=None
    )
    aes_key   = private_key.decrypt(
        base64.b64decode(enc["encrypted_aes"]),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    decrypted = AESGCM(aes_key).decrypt(
        base64.b64decode(enc["nonce"]),
        base64.b64decode(enc["encrypted_data"]),
        None
    )
    elapsed = time.perf_counter() - start
    return decrypted, elapsed


# ─────────────────────────────────────────────
# Benchmark — PQC vs Classical
# Imported by cloud_upload.py:
#   from security import benchmark_encryption
# ─────────────────────────────────────────────
def benchmark_encryption(data: bytes) -> dict:
    """
    Run both PQC and Classical encryption on the same payload
    and return a combined result dict for cloud_upload.py.

    Returns:
        {
            "pqc":       { ...encrypt_with_kyber result... },
            "classical": { ...encrypt_with_classical result... },
            "benchmark": {
                "data_size_bytes",
                "pqc_time_seconds",
                "classical_time_seconds",
                "faster",
                "difference_seconds"
            }
        }
    """
    print("\n[Benchmark] Running PQC vs Classical...")

    pqc_result       = encrypt_with_kyber(data)
    classical_result = encrypt_with_classical(data)

    pqc_time       = pqc_result["encryption_time_seconds"]
    classical_time = classical_result["encryption_time_seconds"]
    faster         = "PQC" if pqc_time < classical_time else "Classical"
    diff           = round(abs(pqc_time - classical_time), 6)

    print(f"[Benchmark] PQC       : {pqc_time:.6f}s")
    print(f"[Benchmark] Classical : {classical_time:.6f}s")
    print(f"[Benchmark] Faster    : {faster} by {diff:.6f}s")

    return {
        "pqc":       pqc_result,
        "classical": classical_result,
        "benchmark": {
            "data_size_bytes":        len(data),
            "pqc_time_seconds":       pqc_time,
            "classical_time_seconds": classical_time,
            "faster":                 faster,
            "difference_seconds":     diff,
        }
    }
    
def benchmark_full(data: bytes) -> dict:
    print("\n[Benchmark] Running Full Encrypt + Decrypt...")

    # ── PQC Encrypt ──
    pqc_enc = encrypt_with_kyber(data)

    # ── PQC Decrypt ──
    pqc_dec_data, pqc_dec_time = decrypt_with_kyber(pqc_enc)

    # ── Classical Encrypt ──
    cls_enc = encrypt_with_classical(data)

    # ── Classical Decrypt ──
    cls_dec_data, cls_dec_time = decrypt_with_classical(cls_enc)

    return {
        "pqc": pqc_enc,
        "classical": cls_enc,
        "benchmark": {
            "pqc_encrypt_time": pqc_enc["encryption_time_seconds"],
            "classical_encrypt_time": cls_enc["encryption_time_seconds"],
            "pqc_decrypt_time": pqc_dec_time,
            "classical_decrypt_time": cls_dec_time,
        }
    }