"""Hybrid first-stage retrieval: BM25 (lexical) + biomedical dense embeddings.

Rankings are fused with Reciprocal Rank Fusion (RRF, Cormack et al. 2009),
which needs no score calibration between the two retrievers.

Phase 1 keeps the dense index as a NumPy matrix on disk (exact cosine search,
fine up to ~100k trials on CPU). Phase 2 swaps this for Qdrant.
"""

import json
import re
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from trialbridge.config import EMBED_MODEL, INDEX_DIR, MODELS_DIR

_TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
STOP = set("""a an the of and or in on for to with without by at from as is are was were be been being this that these those
it its into than then there their them they he she his her patients patient subjects subject participants participant study
trial will may must should can could have has had not no any all who which other such including include""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in STOP and len(t) > 1]


def trial_text(t: dict, with_eligibility: bool = True) -> str:
    parts = [t.get("title") or "", t.get("official_title") or "", " ".join(t.get("conditions") or []),
             " ".join(t.get("keywords") or []), " ".join(x for x in t.get("interventions") or [] if x),
             t.get("summary") or ""]
    if with_eligibility:
        parts.append(t.get("eligibility") or "")
    return "\n".join(p for p in parts if p)


def dense_text(t: dict) -> str:
    # dense encoders truncate (~256-512 tokens): lead with the most discriminative fields
    head = f"{t.get('title') or ''}. Conditions: {', '.join(t.get('conditions') or [])}. "
    return head + (t.get("summary") or "") + " " + (t.get("eligibility") or "")[:800]


_model_cache: dict = {}


def model_path(name: str = EMBED_MODEL) -> str:
    """Download once into a plain folder (Windows without symlink rights breaks the HF cache)."""
    if Path(name).exists():
        return name
    local = MODELS_DIR / name.replace("/", "__")
    if not (local / "config.json").exists():
        from huggingface_hub import snapshot_download

        snapshot_download(name, local_dir=local,
                          allow_patterns=["*.json", "*.txt", "model.safetensors", "1_Pooling/*", "*.model"])
    return str(local)


def get_encoder(name: str = EMBED_MODEL, max_seq: int = 256):
    if name not in _model_cache:
        from sentence_transformers import SentenceTransformer

        _model_cache[name] = SentenceTransformer(model_path(name), device="cpu")
    m = _model_cache[name]
    m.max_seq_length = max_seq
    return m


class HybridIndex:
    def __init__(self, ids: list[str], bm25: BM25Okapi, emb: np.ndarray | None, model: str = EMBED_MODEL,
                 max_seq: int = 256):
        self.ids, self.bm25, self.emb, self.model, self.max_seq = ids, bm25, emb, model, max_seq
        self.pos = {i: n for n, i in enumerate(ids)}

    # ------------------------------------------------------------------ build / persist
    @classmethod
    def build(cls, trials: list[dict], dense: bool = True, model: str = EMBED_MODEL, batch_size: int = 32,
              max_seq: int = 256) -> "HybridIndex":
        ids = [t["trial_id"] for t in trials]
        bm25 = BM25Okapi([tokenize(trial_text(t)) for t in trials])
        emb = None
        if dense:
            enc = get_encoder(model, max_seq)
            emb = enc.encode([dense_text(t) for t in trials], batch_size=batch_size, show_progress_bar=True,
                             normalize_embeddings=True, convert_to_numpy=True).astype(np.float32)
        return cls(ids, bm25, emb, model, max_seq)

    def save(self, name: str, root: Path = INDEX_DIR) -> None:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps({"ids": self.ids, "model": self.model, "max_seq": self.max_seq}))
        if self.emb is not None:
            np.save(d / "emb.npy", self.emb)

    @classmethod
    def load(cls, name: str, trials_by_id: dict[str, dict], root: Path = INDEX_DIR) -> "HybridIndex":
        d = root / name
        meta = json.loads((d / "meta.json").read_text())
        ids = [i for i in meta["ids"] if i in trials_by_id]
        emb = np.load(d / "emb.npy") if (d / "emb.npy").exists() else None
        if emb is not None and len(ids) != len(meta["ids"]):
            keep = [n for n, i in enumerate(meta["ids"]) if i in trials_by_id]
            emb = emb[keep]
        bm25 = BM25Okapi([tokenize(trial_text(trials_by_id[i])) for i in ids])
        return cls(ids, bm25, emb, meta["model"], meta.get("max_seq", 256))

    # ------------------------------------------------------------------ search
    def bm25_scores(self, query: str) -> np.ndarray:
        return np.asarray(self.bm25.get_scores(tokenize(query)), dtype=np.float32)

    def dense_scores(self, query: str) -> np.ndarray | None:
        if self.emb is None:
            return None
        q = get_encoder(self.model, self.max_seq).encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
        return self.emb @ q.astype(np.float32)

    def search(self, query: str, k: int = 100, mode: str = "hybrid", subset: list[str] | None = None,
               rrf_k: int = 60) -> list[tuple[str, float, dict]]:
        """Return [(trial_id, fused_score, {bm25_rank, dense_rank, ...})]."""
        mask = None
        if subset is not None:
            mask = np.zeros(len(self.ids), dtype=bool)
            mask[[self.pos[i] for i in subset if i in self.pos]] = True
        rankings = {}
        if mode in ("bm25", "hybrid"):
            rankings["bm25"] = self.bm25_scores(query)
        if mode in ("dense", "hybrid"):
            ds = self.dense_scores(query)
            if ds is not None:
                rankings["dense"] = ds
        fused = np.zeros(len(self.ids), dtype=np.float64)
        ranks: dict[str, np.ndarray] = {}
        for name, s in rankings.items():
            s = s.copy()
            if mask is not None:
                s[~mask] = -np.inf
            order = np.argsort(-s)
            r = np.empty(len(s), dtype=np.int64)
            r[order] = np.arange(1, len(s) + 1)
            ranks[name] = r
            fused += 1.0 / (rrf_k + r)
        if mask is not None:
            fused[~mask] = -1
        top = np.argsort(-fused)[:k]
        return [(self.ids[i], float(fused[i]), {f"{n}_rank": int(r[i]) for n, r in ranks.items()}) for i in top
                if fused[i] > 0]
