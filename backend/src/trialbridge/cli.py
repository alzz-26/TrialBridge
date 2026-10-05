"""TrialBridge command line.

  trialbridge ingest   --per 150                 # demo corpus from ClinicalTrials.gov
  trialbridge synthea  --n 300                   # generate + load synthetic patients
  trialbridge parse                               # (re)parse eligibility criteria
  trialbridge index                               # build BM25 + dense index
  trialbridge serve                               # FastAPI on :8000
  trialbridge trec-fetch / trec-eval              # TREC CT 2021 benchmark
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from trialbridge import config, db

# Conditions Synthea generates often, so the demo cohort and corpus overlap.
DEMO_CONDITIONS = [
    "Type 2 Diabetes", "Prediabetes", "Hypertension", "Chronic Kidney Disease", "Heart Failure",
    "Coronary Artery Disease", "Atrial Fibrillation", "COPD", "Asthma", "Obesity", "Hyperlipidemia",
    "Osteoarthritis", "Breast Cancer", "Lung Cancer", "Colorectal Cancer", "Prostate Cancer",
    "Alzheimer Disease", "Depression", "Stroke", "Anemia",
]


def _use_db(path: str | None):
    if path:
        config.DB_PATH = Path(path)


def cmd_ingest(a):
    from trialbridge.criteria.parser import parse_eligibility
    from trialbridge.ingest.ctgov import CTGovClient

    client = CTGovClient()
    conds = a.conditions.split(";") if a.conditions else DEMO_CONDITIONS
    total = 0
    with db.session() as conn:
        for cond in conds:
            n = 0
            for t in client.search(condition=cond, status=a.status or None, limit=a.per):
                if not t["trial_id"] or not t.get("eligibility"):
                    continue
                db.upsert_trial(conn, t)
                db.replace_criteria(conn, t["trial_id"], parse_eligibility(
                    t["eligibility"], t["min_age_years"], t["max_age_years"], t["sex"]))
                n += 1
            conn.commit()
            total += n
            print(f"  {cond:28s} {n:5d} trials")
        print(f"ingested {total} trials -> {config.DB_PATH}  (total in DB: "
              f"{conn.execute('SELECT COUNT(*) FROM trials').fetchone()[0]})")


def cmd_parse(a):
    from trialbridge.criteria.parser import parse_eligibility, parse_stats

    agg = {"criteria": 0, "parsed": 0, "fully_parsed": 0, "predicates": {}}
    with db.session() as conn:
        rows = conn.execute("SELECT trial_id, eligibility, min_age_years, max_age_years, sex FROM trials").fetchall()
        for r in rows:
            crit = parse_eligibility(r["eligibility"], r["min_age_years"], r["max_age_years"], r["sex"])
            db.replace_criteria(conn, r["trial_id"], crit)
            s = parse_stats(crit)
            agg["criteria"] += s["criteria"]
            agg["parsed"] += s["parsed"]
            agg["fully_parsed"] += s["fully_parsed"]
            for k, v in s["predicates"].items():
                agg["predicates"][k] = agg["predicates"].get(k, 0) + v
    agg["trials"] = len(rows)
    agg["coverage"] = round(agg["parsed"] / max(agg["criteria"], 1), 4)
    agg["full_coverage"] = round(agg["fully_parsed"] / max(agg["criteria"], 1), 4)
    print(json.dumps(agg, indent=2))
    out = config.RESULTS_DIR / f"parse_stats_{config.DB_PATH.stem}.json"
    out.write_text(json.dumps(agg, indent=2))


def cmd_synthea(a):
    from trialbridge.patients.profile import load_synthea_dir

    out_dir = config.SYNTHEA_DIR
    fhir = out_dir / "fhir"
    if not a.skip_generate:
        jar = config.REPO_ROOT / "tools" / "synthea.jar"
        if not jar.exists():
            sys.exit(f"missing {jar} - download synthea-with-dependencies.jar from "
                     "https://github.com/synthetichealth/synthea/releases")
        if fhir.exists():
            shutil.rmtree(fhir)
        tmp = config.DATA_DIR / "tmp"
        tmp.mkdir(exist_ok=True)
        cmd = ["java", f"-Djava.io.tmpdir={tmp}", "-Xmx3g", "-jar", str(jar), "-p", str(a.n), "-s", str(a.seed), "-a", a.ages,
               "--exporter.baseDirectory", str(out_dir), "--exporter.years_of_history", "10",
               "--exporter.fhir.export", "true", "--exporter.csv.export", "false",
               "--exporter.hospital.fhir.export", "false", "--exporter.practitioner.fhir.export", "false",
               "--generate.only_alive_patients", "true", a.state]
        print(" ".join(cmd))
        subprocess.run(cmd, check=True, cwd=config.REPO_ROOT / "tools")
    t0 = time.time()
    patients = load_synthea_dir(fhir)
    with db.session() as conn:
        conn.execute("DELETE FROM patients WHERE source = 'synthea'")
        for p in patients:
            db.upsert_patient(conn, p["patient_id"], "synthea", p["name"], p)
    print(f"loaded {len(patients)} Synthea patients in {time.time() - t0:.1f}s")


def cmd_index(a):
    from trialbridge.matching.retrieval import HybridIndex

    with db.session() as conn:
        trials = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM trials ORDER BY trial_id")]
    t0 = time.time()
    idx = HybridIndex.build(trials, dense=not a.no_dense, batch_size=a.batch, max_seq=a.max_seq)
    idx.save(a.name)
    print(f"indexed {len(trials)} trials as '{a.name}' in {time.time() - t0:.0f}s")


def cmd_trec_fetch(a):
    from trialbridge.criteria.parser import parse_eligibility
    from trialbridge.eval.trec import load_qrels
    from trialbridge.ingest.ctgov import CTGovClient

    ids = sorted({d for q in load_qrels().values() for d in q})
    with db.session() as conn:
        have = {r[0] for r in conn.execute("SELECT trial_id FROM trials")}
        todo = [i for i in ids if i not in have]
        print(f"{len(ids)} judged trials, {len(todo)} to fetch")
        client = CTGovClient(pause=0.2)
        for n, t in enumerate(client.by_ids(todo), 1):
            db.upsert_trial(conn, t)
            db.replace_criteria(conn, t["trial_id"], parse_eligibility(
                t["eligibility"], t["min_age_years"], t["max_age_years"], t["sex"]))
            if n % 1000 == 0:
                conn.commit()
                print(f"  {n}/{len(todo)}")


def cmd_trec_eval(a):
    from trialbridge.eval.trec import run
    from trialbridge.matching.retrieval import HybridIndex

    with db.session() as conn:
        trials = {r["trial_id"]: db.row_to_dict(r) for r in conn.execute("SELECT * FROM trials")}
        criteria: dict[str, list] = {}
        for r in conn.execute("SELECT trial_id, kind, text, predicates FROM criteria ORDER BY trial_id, position"):
            criteria.setdefault(r["trial_id"], []).append(
                {"kind": r["kind"], "text": r["text"], "predicates": json.loads(r["predicates"])})
    idx = HybridIndex.load(a.name, trials)
    run(idx, trials, criteria, settings=a.settings.split(","), limit_topics=a.limit)


def cmd_serve(a):
    import uvicorn

    uvicorn.run("trialbridge.api:app", host=a.host, port=a.port, reload=a.reload)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="trialbridge")
    ap.add_argument("--db", help="SQLite path (default data/trialbridge.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest")
    s.add_argument("--conditions", help="';'-separated list (default: demo set)")
    s.add_argument("--per", type=int, default=150)
    s.add_argument("--status", default="RECRUITING")
    s.set_defaults(fn=cmd_ingest)

    sub.add_parser("parse").set_defaults(fn=cmd_parse)

    s = sub.add_parser("synthea")
    s.add_argument("--n", type=int, default=300)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--ages", default="25-85")
    s.add_argument("--state", default="Massachusetts")
    s.add_argument("--skip-generate", action="store_true")
    s.set_defaults(fn=cmd_synthea)

    s = sub.add_parser("index")
    s.add_argument("--name", default="main")
    s.add_argument("--no-dense", action="store_true")
    s.add_argument("--batch", type=int, default=32)
    s.add_argument("--max-seq", type=int, default=256, help="encoder token limit (128 is ~2x faster on CPU)")
    s.set_defaults(fn=cmd_index)

    sub.add_parser("trec-fetch").set_defaults(fn=cmd_trec_fetch)
    s = sub.add_parser("trec-eval")
    s.add_argument("--name", default="trec")
    s.add_argument("--settings", default="rerank,corpus")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_trec_eval)

    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    _use_db(a.db)
    a.fn(a)


if __name__ == "__main__":
    main()
