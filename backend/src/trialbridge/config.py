"""Central paths and settings. Override with environment variables."""

import os
from pathlib import Path

# torch only - stop transformers from importing a system-wide TensorFlow
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("TB_DATA_DIR", REPO_ROOT / "data"))
DB_PATH = Path(os.environ.get("TB_DB_PATH", DATA_DIR / "trialbridge.db"))
INDEX_DIR = DATA_DIR / "index"
MODELS_DIR = REPO_ROOT / ".cache" / "models"
SYNTHEA_DIR = DATA_DIR / "synthea"
TREC_DIR = DATA_DIR / "trec"
RESULTS_DIR = REPO_ROOT / "results"

# keep model downloads inside the project (C: on the dev machine is full)
os.environ.setdefault("HF_HOME", str(REPO_ROOT / ".cache" / "hf"))

# Biomedical sentence encoder used for dense retrieval.
# PubMedBERT fine-tuned as a sentence encoder on PubMed (safetensors weights).
EMBED_MODEL = os.environ.get("TB_EMBED_MODEL", "NeuML/pubmedbert-base-embeddings")

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
USER_AGENT = "TrialBridge/0.1 (academic capstone project)"

for d in (DATA_DIR, INDEX_DIR, MODELS_DIR, SYNTHEA_DIR, TREC_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
