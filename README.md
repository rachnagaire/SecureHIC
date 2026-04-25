# Quantum-Resilient Secure Data Pipeline for Healthcare Claims

A production-style data pipeline that ingests structured Medicare/Medicaid claims from the **CMS Blue Button sandbox**, protects them with **NIST-standardized post-quantum cryptography** (ML-KEM + ML-DSA), and processes them through a **Bronze / Silver / Gold medallion architecture** on Google Cloud. Includes parallel processing benchmarks against a classical RSA-4096 + AES-256-GCM baseline and a machine-learning fraud-detection module.

This repository accompanies the paper:

> Rachana Gaire, _A Quantum-Resilient Secure Data Pipeline for Healthcare Claims: Integrating Post-Quantum Cryptography, Parallel Processing, and Machine Learning-Based Fraud Detection_, Middle Tennessee State University, 2026.

---

## Table of Contents

1. [Motivation](#motivation)
2. [Architecture](#architecture)
3. [Key Results](#key-results)
4. [Repository Structure](#repository-structure)
5. [Requirements](#requirements)
6. [Installation](#installation)
7. [Configuration](#configuration)
8. [Usage](#usage)
9. [Reproducing the Paper's Experiments](#reproducing-the-papers-experiments)
10. [Data and Privacy](#data-and-privacy)
11. [Limitations](#limitations)
12. [Citing This Work](#citing-this-work)
13. [License](#license)
14. [Contact](#contact)

---

## Motivation

Healthcare claim records are among the longest-lived categories of sensitive personal data and are exposed to a "harvest now, decrypt later" threat: an adversary can store ciphertext today and decrypt it once a cryptanalytically relevant quantum computer becomes available. RSA and ECC, which underpin most current healthcare cryptography, are broken by Shor's algorithm.

In August 2024, NIST finalized the first post-quantum standards — **ML-KEM (FIPS 203)** for key encapsulation and **ML-DSA (FIPS 204)** for digital signatures. This project measures the **end-to-end practical cost** of deploying these primitives in a realistic healthcare data pipeline, and verifies that downstream analytics (fraud detection) remain compatible.

---

## Architecture

The system is organized into five layers:

|          Layer | Purpose                            | Components                                               |
| -------------: | ---------------------------------- | -------------------------------------------------------- |
|        1. User | Identify clients of the pipeline   | Hospitals, Insurers, Patients, Admins, Auditors, CMS API |
| 2. API Gateway | Authenticate and protect transport | OAuth 2.0, TLS 1.3, HIPAA filter                         |
|        3. RBAC | Role-based authorization           | Adjuster, Provider, Administrator, Auditor               |
|         4. PQC | Quantum-resilient cryptography     | **ML-KEM**, **ML-DSA**, AES-256-GCM, Cloud KMS           |
|        5. Data | Medallion storage on Google Cloud  | Bronze → Silver → Gold + GCS + BigQuery                  |

Bulk encryption uses the standard **KEM-then-symmetric** pattern: ML-KEM encapsulates a 256-bit AES session key, AES-256-GCM encrypts the claim payload, and ML-DSA signs the ciphertext for integrity and authenticity.

See [`architecture_diagram.pdf`](architecture_diagram.pdf) for the full block diagram.

---

## Key Results

Measured on structured ExplanationOfBenefit (EOB) claims from the CMS Blue Button sandbox:

| Metric              | Classical (RSA-4096 + AES-256-GCM) | Post-Quantum (ML-KEM + ML-DSA) |          Overhead |
| ------------------- | ---------------------------------: | -----------------------------: | ----------------: |
| Encryption time     |                             0.42 s |                         0.68 s |         **+62 %** |
| Decryption time     |                             0.31 s |                         0.51 s |             +65 % |
| Storage footprint   |                          30,810 KB |                      35,364 KB |         **+32 %** |
| End-to-end pipeline |               37.51 s (sequential) |             30.88 s (parallel) | **1.21× speedup** |

**Headline finding:** PQC overhead is real but is _not_ the bottleneck. Network and cloud I/O dominate end-to-end runtime; cryptographic computation accounts for only 1–2 seconds of the full pipeline.

Fraud detection (secondary, preliminary):

| Model               |  Accuracy | Recall |   ROC-AUC |
| ------------------- | --------: | -----: | --------: |
| Logistic Regression |     0.563 |  0.917 |     0.743 |
| **Random Forest**   | **0.939** |  0.500 |     0.739 |
| XGBoost             |     0.927 |  0.500 | **0.778** |
| Isolation Forest    |     0.981 |  0.083 |     0.474 |

> Fraud results are preliminary: only 50 of 4,000 sandbox claims are labeled fraudulent (1.25 %), so recall estimates have high variance.

---

## Repository Structure

```
.
├── README.md                       # This file
├── requirements.txt                # Python dependencies
├── architecture_diagram.py         # Generates the architecture figure
├── architecture_diagram.pdf        # Pre-rendered architecture figure
│
├── src/
│   ├── ingestion/                  # CMS Blue Button OAuth client + pagination
│   │   ├── oauth_client.py
│   │   └── fetch_claims.py
│   ├── crypto/                     # Encryption modules
│   │   ├── classical.py            # RSA-4096 + AES-256-GCM
│   │   ├── pqc.py                  # ML-KEM + ML-DSA + AES-256-GCM
│   │   └── benchmarks.py
│   ├── pipeline/                   # Bronze / Silver / Gold transformations
│   │   ├── bronze.py
│   │   ├── silver.py
│   │   └── gold.py
│   ├── parallel/                   # Multi-worker execution harness
│   │   └── runner.py
│   ├── fraud/                      # ML fraud-detection models
│   │   ├── features.py
│   │   ├── train.py
│   │   └── evaluate.py
│   └── cloud/                      # GCS + BigQuery clients
│       ├── gcs_client.py
│       └── bq_client.py
│
├── notebooks/                      # Jupyter notebooks for analysis
│   ├── 01_crypto_benchmarks.ipynb
│   ├── 02_parallel_scaling.ipynb
│   └── 03_fraud_detection.ipynb
│
├── data/
│   ├── bronze/                     # (gitignored) raw FHIR + ciphertext
│   ├── silver/                     # (gitignored) processed CSVs
│   └── gold/                       # (gitignored) aggregates
│
├── results/                        # Benchmark CSVs and plots
└── tests/                          # Unit tests
```

> **Note:** Adjust this tree to match your actual layout. Treat it as a template.

---

## Requirements

- **Python** ≥ 3.10
- **Google Cloud account** with the following enabled:
  - Cloud Storage (GCS)
  - BigQuery
  - Secret Manager (recommended for key storage)
- **CMS Blue Button sandbox credentials** (free; register at [bluebutton.cms.gov](https://bluebutton.cms.gov))

### Python dependencies

The PQC layer is built on `liboqs-python`, the Open Quantum Safe project's Python bindings to ML-KEM and ML-DSA.

```text
# requirements.txt (minimum)
cryptography>=42.0          # RSA, AES-GCM baseline
liboqs-python>=0.10.0       # ML-KEM + ML-DSA
google-cloud-storage>=2.14
google-cloud-bigquery>=3.17
google-cloud-secret-manager>=2.18
requests>=2.31              # CMS Blue Button OAuth
pandas>=2.2
numpy>=1.26
scikit-learn>=1.4           # Logistic Regression, Random Forest, Isolation Forest
xgboost>=2.0
imbalanced-learn>=0.12      # SMOTE for fraud detection
matplotlib>=3.8
```

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/<your-user>/quantum-resilient-claims.git
cd quantum-resilient-claims

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install the liboqs C library (required by liboqs-python)
#    See https://github.com/open-quantum-safe/liboqs for platform-specific
#    instructions. On macOS/Linux:
git clone --depth=1 https://github.com/open-quantum-safe/liboqs
cmake -S liboqs -B liboqs/build -DBUILD_SHARED_LIBS=ON
cmake --build liboqs/build --parallel 4
sudo cmake --install liboqs/build
```

---

## Configuration

Create a `.env` file in the repo root (do **not** commit this):

```bash
# CMS Blue Button OAuth
CMS_CLIENT_ID=your_client_id
CMS_CLIENT_SECRET=your_client_secret
CMS_REDIRECT_URI=http://localhost:8000/callback

# Google Cloud
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GCP_PROJECT_ID=your-project-id
GCS_BUCKET_BRONZE=claims-bronze
GCS_BUCKET_SILVER=claims-silver
GCS_BUCKET_GOLD=claims-gold
BQ_DATASET=claims_analytics
```

---

## Usage

### Quick start — full pipeline end-to-end

```bash
python -m src.pipeline.run \
    --workers 4 \
    --crypto pqc \
    --layers bronze silver gold
```

### Run individual stages

**1. Ingest claims from CMS Blue Button:**

```bash
python -m src.ingestion.fetch_claims --output data/bronze/raw_claims.json
```

**2. Encrypt the Bronze layer (PQC):**

```bash
python -m src.crypto.pqc \
    --input data/bronze/raw_claims.json \
    --output data/bronze/claims.enc \
    --signature data/bronze/claims.sig
```

**3. Transform Bronze → Silver:**

```bash
python -m src.pipeline.silver \
    --input data/bronze/raw_claims.json \
    --output data/silver/claims.csv
```

**4. Aggregate Silver → Gold:**

```bash
python -m src.pipeline.gold \
    --input data/silver/claims.csv \
    --output data/gold/aggregates.csv
```

### Run fraud detection

```bash
python -m src.fraud.train --model random_forest
python -m src.fraud.evaluate --model random_forest --report results/rf_report.json
```

---

## Reproducing the Paper's Experiments

All four experiments from the paper can be reproduced from the repository root:

| Experiment                         | Command                                           | Output                         |
| ---------------------------------- | ------------------------------------------------- | ------------------------------ |
| Crypto benchmark (Sec. IV-A, IV-B) | `python -m src.crypto.benchmarks --runs 10`       | `results/crypto_bench.csv`     |
| Parallel scaling (Sec. IV-C, IV-D) | `python -m src.parallel.runner --workers 1 2 4 8` | `results/parallel_scaling.csv` |
| Stage-wise timing (Sec. IV-E)      | `python -m src.pipeline.run --profile`            | `results/stage_times.csv`      |
| Fraud detection (Sec. IV-F)        | `python -m src.fraud.evaluate --all-models`       | `results/fraud_report.json`    |

The plots in the paper (Figures 2–4) are regenerated by the notebooks under `notebooks/`.

---

## Data and Privacy

This project uses the **CMS Blue Button sandbox**, which serves _synthetic_ claim data that mirrors the structure of production Medicare records but contains no real PHI. The pipeline nonetheless treats the data as if it were real:

- Direct identifiers are **hashed** (SHA-256) at the Silver layer.
- Sensitive fields are **encrypted at rest** at the Bronze layer (RSA/AES baseline or ML-KEM/ML-DSA + AES).
- Only **non-sensitive, de-identified features** are loaded into BigQuery for analytics.
- All data files are **gitignored** by default.

> If you adapt this pipeline for production data, you are responsible for HIPAA, state-level, and institutional compliance. This repository is a research artifact, not a certified clinical system.

---

## Limitations

Honest limitations of this work, mirroring Section V of the paper:

1. **I/O dominates runtime.** Reported 1.21× speedup is bounded by network and cloud-storage latency, not by cryptographic compute. Speedups will differ in other deployment topologies.
2. **PQC storage overhead is visible.** A 32 % increase in stored ciphertext is manageable but non-trivial at petabyte scale.
3. **Fraud results are preliminary.** Class imbalance (1.25 % fraud) and a small absolute number of fraud labels (50) limit the precision of recall and AUC estimates. Results should not be used to compare fraud-detection algorithms in absolute terms.
4. **Sandbox data limits generalization.** CMS Blue Button sandbox data is synthetic; results may differ on production claim distributions, particularly for rare fraud patterns.
5. **Single-cloud evaluation.** All experiments run on Google Cloud. Performance characteristics on AWS, Azure, or on-prem deployments are not measured here.

---

## Citing This Work

If you use this code or its results, please cite:

```bibtex
@misc{gaire2026quantumresilient,
  author       = {Rachana Gaire},
  title        = {A Quantum-Resilient Secure Data Pipeline for Healthcare Claims:
                  Integrating Post-Quantum Cryptography, Parallel Processing,
                  and Machine Learning-Based Fraud Detection},
  year         = {2026},
  institution  = {Middle Tennessee State University},
  howpublished = {\url{https://github.com/rachnagaire/SecureHIC}}
}
```

---

## License

Released under the MIT License. See [`LICENSE`](LICENSE) for details.

> The `liboqs` library is distributed separately under its own MIT License. CMS Blue Button data is subject to CMS terms of use.

---

## Contact

**Rachana Gaire**
Department of Computer Science, Middle Tennessee State University
University Email: rg6d@mtmail.mtsu.edu
Personal Email: rachnagaire12@gmail.com

For issues or questions about reproducing the experiments, please open a GitHub issue.
