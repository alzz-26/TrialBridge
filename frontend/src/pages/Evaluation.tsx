import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, Spinner } from "../components";

const METRICS = ["ndcg@10", "p@10", "p@10_any", "recall@100", "mrr"];
const SYSTEMS = ["bm25", "dense", "hybrid", "hybrid+criteria"];
const NAMES: Record<string, string> = {
  bm25: "BM25 (lexical baseline)",
  dense: "Dense (PubMedBERT)",
  hybrid: "Hybrid RRF",
  "hybrid+criteria": "TrialBridge: hybrid + criteria evaluator",
};

export default function Evaluation() {
  const [data, setData] = useState<Record<string, any> | null>(null);
  useEffect(() => { api.evaluation().then(setData); }, []);
  if (!data) return <Spinner />;
  const trec = data["trec2021"];
  const parse = Object.entries(data).filter(([k]) => k.startsWith("parse_stats"));

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="text-lg font-semibold">TREC Clinical Trials 2021</div>
        <p className="mt-1 text-sm text-slate-500">
          75 patient topics · graded judgements (2 = eligible, 1 = excluded, 0 = not relevant). P@10 counts eligible trials only;
          P@10_any also counts excluded-but-topical trials.
        </p>
        {!trec && <div className="mt-4 text-sm text-slate-500">Run <code className="rounded bg-slate-100 px-1">trialbridge --db data/trec/trec.db trec-eval</code> to populate.</div>}
        {trec && Object.entries(trec.settings as Record<string, any>).map(([setting, rows]) => (
          <div key={setting} className="mt-5">
            <div className="mb-2 text-sm font-semibold">
              {setting === "rerank" ? "Re-ranking each topic's judged pool" : `Retrieval from the full judged corpus (${trec.n_trials} trials)`}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b text-left text-xs uppercase text-slate-500">
                  <th className="py-2 pr-4">System</th>{METRICS.map((m) => <th key={m} className="px-3 py-2 text-right">{m}</th>)}
                </tr></thead>
                <tbody>
                  {SYSTEMS.filter((s) => rows[s]).map((s) => {
                    const best = (m: string) => Math.max(...SYSTEMS.filter((x) => rows[x]).map((x) => rows[x][m]));
                    return (
                      <tr key={s} className="border-b border-slate-100">
                        <td className="py-2 pr-4">{NAMES[s]}</td>
                        {METRICS.map((m) => (
                          <td key={m} className={`px-3 py-2 text-right tabular-nums ${rows[s][m] === best(m) ? "font-semibold text-brand-700" : ""}`}>
                            {rows[s][m].toFixed(4)}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </Card>

      {parse.map(([k, s]) => (
        <Card key={k} className="p-5">
          <div className="text-lg font-semibold">Criteria parser coverage <span className="text-sm font-normal text-slate-400">({k.replace("parse_stats_", "")})</span></div>
          <div className="mt-3 flex flex-wrap gap-8 text-sm">
            <div><div className="text-2xl font-semibold">{s.trials.toLocaleString()}</div><div className="text-slate-500">trials</div></div>
            <div><div className="text-2xl font-semibold">{s.criteria.toLocaleString()}</div><div className="text-slate-500">free-text criteria</div></div>
            <div><div className="text-2xl font-semibold">{(s.coverage * 100).toFixed(1)}%</div><div className="text-slate-500">yield ≥ 1 predicate</div></div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            {Object.entries(s.predicates as Record<string, number>).sort((a, b) => b[1] - a[1]).map(([t, n]) => (
              <span key={t} className="rounded bg-slate-100 px-2 py-1">{t}: {n.toLocaleString()}</span>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}
