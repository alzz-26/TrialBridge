"""TREC Clinical Trials 2021 benchmark harness.

Topics: 75 synthetic patient case descriptions (free text).
Qrels : 35,832 judgements, 0 = not relevant, 1 = excluded, 2 = eligible.
        https://www.trec-cds.org/2021.html

The judged trials are fetched live from ClinicalTrials.gov (current record
versions; the official corpus is an April-2021 snapshot - noted in the report).

Two settings:
  * rerank : rank each topic's judged pool (the TrialGPT-Ranking setup)
  * corpus : retrieve from the union of all judged trials (~26k)

Systems (ablation):
  bm25 | dense | hybrid (RRF) | hybrid+criteria (TrialBridge: retrieval + deterministic eligibility)
"""

import json
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import numpy as np

from trialbridge.config import RESULTS_DIR, TREC_DIR
from trialbridge.matching.evaluator import eval_trial
from trialbridge.patients.profile import from_text


def load_topics(path: Path = TREC_DIR / "topics2021.xml") -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {t.attrib["number"]: re.sub(r"\s+", " ", t.text or "").strip() for t in root.findall("topic")}


def load_qrels(path: Path = TREC_DIR / "qrels2021.txt") -> dict[str, dict[str, int]]:
    q: dict[str, dict[str, int]] = defaultdict(dict)
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 4:
            q[parts[0]][parts[2]] = int(parts[3])
    return q


# ----------------------------------------------------------------------------- metrics
def ndcg_at(ranked: list[str], rels: dict[str, int], k: int = 10) -> float:
    dcg = sum((2 ** rels.get(d, 0) - 1) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    ideal = sorted(rels.values(), reverse=True)[:k]
    idcg = sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def p_at(ranked, rels, k=10, level=2):
    return sum(rels.get(d, 0) >= level for d in ranked[:k]) / k


def recall_at(ranked, rels, k=100, level=2):
    tot = sum(v >= level for v in rels.values())
    return sum(rels.get(d, 0) >= level for d in ranked[:k]) / tot if tot else 0.0


def mrr(ranked, rels, level=2):
    for i, d in enumerate(ranked):
        if rels.get(d, 0) >= level:
            return 1 / (i + 1)
    return 0.0


def metrics(ranked, rels) -> dict:
    return {"ndcg@10": ndcg_at(ranked, rels, 10), "p@10": p_at(ranked, rels, 10), "p@10_any": p_at(ranked, rels, 10, 1),
            "recall@100": recall_at(ranked, rels, 100), "mrr": mrr(ranked, rels)}


def mean(rows: list[dict]) -> dict:
    return {k: round(float(np.mean([r[k] for r in rows])), 4) for k in rows[0]} if rows else {}


# ----------------------------------------------------------------------------- runner
def run(index, trials: dict, criteria: dict, settings=("rerank", "corpus"), limit_topics: int | None = None) -> dict:
    from trialbridge.matching.engine import W_ELIGIBILITY, W_RETRIEVAL

    topics = load_topics()
    qrels = load_qrels()
    tids = [t for t in sorted(topics, key=int) if t in qrels][:limit_topics]
    have = set(index.ids)
    out = {"n_topics": len(tids), "n_trials": len(have), "settings": {}}
    for setting in settings:
        per_sys: dict[str, list[dict]] = defaultdict(list)
        for t in tids:
            text = topics[t]
            rels = {d: r for d, r in qrels[t].items() if d in have}
            subset = list(rels) if setting == "rerank" else None
            k = len(subset) if subset else 1000
            for mode in ("bm25", "dense", "hybrid"):
                if mode == "dense" and index.emb is None:
                    continue
                hits = index.search(text, k=k, mode=mode, subset=subset)
                per_sys[mode].append(metrics([h[0] for h in hits], rels))
                if mode == "hybrid":
                    profile = from_text(text, patient_id=f"topic-{t}")
                    top = hits[0][1] if hits else 1
                    # rerank the hybrid top-100 with the eligibility evaluator
                    head, tail = hits[:100], hits[100:]
                    scored = []
                    for tid, s, _ in head:
                        ev = eval_trial(criteria.get(tid, []), profile)
                        scored.append((tid, W_RETRIEVAL * s / top + W_ELIGIBILITY * ev["score"]))
                    scored.sort(key=lambda x: -x[1])
                    ranked = [x[0] for x in scored] + [h[0] for h in tail]
                    per_sys["hybrid+criteria"].append(metrics(ranked, rels))
        out["settings"][setting] = {s: mean(rows) for s, rows in per_sys.items()}
        print(f"\n== {setting} ==")
        for s, m in out["settings"][setting].items():
            print(f"  {s:18s} " + "  ".join(f"{k}={v:.4f}" for k, v in m.items()))
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "trec2021.json").write_text(json.dumps(out, indent=2))
    return out
