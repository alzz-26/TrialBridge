import { useEffect, useMemo, useState } from "react";
import { Search, User } from "lucide-react";
import { api, type PatientBrief, type Profile, type TrialMatch } from "../api";
import { Card, CriteriaTable, Expander, ScoreBar, Spinner, VerdictBadge, cx } from "../components";

type Mode = "cohort" | "text";

const EXAMPLE =
  "62-year-old man with type 2 diabetes for 10 years, on metformin. HbA1c 8.4%, eGFR 58, BMI 32. " +
  "Has hypertension. No history of heart failure or stroke.";

export default function PatientMatch() {
  const [mode, setMode] = useState<Mode>("cohort");
  const [patients, setPatients] = useState<PatientBrief[]>([]);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState(EXAMPLE);
  const [retrieval, setRetrieval] = useState("hybrid");
  const [recruiting, setRecruiting] = useState(true);
  const [result, setResult] = useState<{ profile: Profile; query: string; results: TrialMatch[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.patients().then((r) => setPatients(r.results)).catch((e) => setError(String(e)));
  }, []);

  const shown = useMemo(() => {
    const f = filter.toLowerCase();
    return patients.filter((p) => !f || p.name.toLowerCase().includes(f) || p.conditions.some((c) => c.toLowerCase().includes(f)));
  }, [patients, filter]);

  async function run(body: object) {
    setLoading(true);
    setError(null);
    try {
      setResult(await api.matchPatient({ ...body, mode: retrieval, recruiting_only: recruiting, k: 20 }));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
      <div className="space-y-4">
        <Card className="p-4">
          <div className="mb-3 flex rounded-lg bg-slate-100 p-1 text-sm">
            {(["cohort", "text"] as Mode[]).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={cx("flex-1 rounded-md px-3 py-1.5 font-medium", mode === m ? "bg-white shadow-sm" : "text-slate-500")}>
                {m === "cohort" ? "Synthea cohort" : "Describe a patient"}
              </button>
            ))}
          </div>

          {mode === "cohort" ? (
            <>
              <div className="relative mb-2">
                <Search size={16} className="absolute left-2.5 top-2.5 text-slate-400" />
                <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by name or condition"
                  className="w-full rounded-lg border border-slate-200 py-2 pl-8 pr-3 text-sm outline-none focus:border-brand-500" />
              </div>
              <ul className="max-h-[420px] divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
                {shown.slice(0, 200).map((p) => (
                  <li key={p.patient_id}>
                    <button onClick={() => { setSelected(p.patient_id); run({ patient_id: p.patient_id }); }}
                      className={cx("w-full px-3 py-2 text-left text-sm hover:bg-slate-50", selected === p.patient_id && "bg-brand-50")}>
                      <div className="font-medium">{p.name} <span className="font-normal text-slate-500">· {Math.round(p.age)}{p.sex?.[0]}</span></div>
                      <div className="truncate text-xs text-slate-500">{p.conditions.join(", ") || "no mapped chronic conditions"}</div>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="mt-1 text-xs text-slate-400">{shown.length} of {patients.length} synthetic patients</div>
            </>
          ) : (
            <>
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8}
                className="w-full rounded-lg border border-slate-200 p-3 text-sm outline-none focus:border-brand-500" />
              <button onClick={() => run({ text })}
                className="mt-2 w-full rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
                Find matching trials
              </button>
            </>
          )}
        </Card>

        <Card className="space-y-3 p-4 text-sm">
          <div className="font-semibold">Settings</div>
          <label className="flex items-center justify-between">
            <span>Retrieval</span>
            <select value={retrieval} onChange={(e) => setRetrieval(e.target.value)} className="rounded-md border border-slate-200 px-2 py-1">
              <option value="hybrid">Hybrid (BM25 + dense)</option>
              <option value="bm25">BM25 only</option>
              <option value="dense">Dense only</option>
            </select>
          </label>
          <label className="flex items-center justify-between">
            <span>Recruiting trials only</span>
            <input type="checkbox" checked={recruiting} onChange={(e) => setRecruiting(e.target.checked)} />
          </label>
        </Card>
      </div>

      <div className="min-w-0 space-y-4">
        {error && <Card className="border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</Card>}
        {loading && <Spinner label="Retrieving and checking criteria" />}
        {!loading && !result && (
          <Card className="flex flex-col items-center p-12 text-center text-slate-500">
            <User size={36} className="mb-3 text-slate-300" />
            Pick a synthetic patient or describe one to see ranked trials with a per-criterion explanation.
          </Card>
        )}
        {!loading && result && <Results r={result} />}
      </div>
    </div>
  );
}

function Results({ r }: { r: { profile: Profile; query: string; results: TrialMatch[] } }) {
  const p = r.profile;
  const counts = { eligible: 0, possibly_eligible: 0, ineligible: 0 };
  r.results.forEach((x) => counts[x.verdict]++);
  return (
    <>
      <Card className="p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="text-lg font-semibold">{p.name}</div>
          <div className="text-sm text-slate-500">{p.age != null && `${Math.round(p.age)} y`} {p.sex?.toLowerCase()}</div>
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {[...new Set(p.conditions.filter((c) => c.concept && c.active !== false).map((c) => c.display))].slice(0, 14).map((d) => (
            <span key={d} className="rounded-md bg-orange-50 px-2 py-0.5 text-xs text-orange-800">{d}</span>
          ))}
          {Object.entries(p.labs).slice(0, 10).map(([k, v]) => (
            <span key={k} className="rounded-md bg-sky-50 px-2 py-0.5 font-mono text-xs text-sky-800">{k} {v.value}</span>
          ))}
          {p.negated?.map((n) => <span key={n} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-500 line-through">{n}</span>)}
        </div>
        <div className="mt-3 flex gap-4 text-sm">
          <span className="text-emerald-700">{counts.eligible} eligible</span>
          <span className="text-amber-700">{counts.possibly_eligible} possibly</span>
          <span className="text-rose-700">{counts.ineligible} ineligible</span>
          <span className="text-slate-400">in top {r.results.length}</span>
        </div>
      </Card>

      {r.results.map((m, i) => (
        <Card key={m.trial.trial_id} className="p-4">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 w-6 shrink-0 text-right text-sm font-semibold text-slate-400">{i + 1}</div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <VerdictBadge v={m.verdict} />
                <a href={`https://clinicaltrials.gov/study/${m.trial.trial_id}`} target="_blank" rel="noreferrer"
                  className="font-mono text-xs text-brand-600 hover:underline">{m.trial.trial_id}</a>
                <span className="text-xs text-slate-400">{m.trial.phase} · {m.trial.status?.toLowerCase().replace(/_/g, " ")}</span>
              </div>
              <div className="mt-1 font-medium leading-snug">{m.trial.title}</div>
              <div className="mt-1 text-xs text-slate-500">{m.trial.conditions.slice(0, 5).join(" · ")}</div>
              <div className="mt-3 grid grid-cols-[1fr_auto] items-center gap-3">
                <ScoreBar e={m} />
                <div className="text-xs tabular-nums text-slate-500">
                  {m.passed}✓ {m.unknown}? {m.failed}✗ · score {m.final_score.toFixed(2)}
                </div>
              </div>
              <div className="mt-3">
                <Expander title="Why? Criterion-by-criterion explanation">
                  <CriteriaTable criteria={m.criteria} />
                  <div className="mt-2 text-xs text-slate-400">
                    retrieval rank {m.retrieval_rank}{m.bm25_rank ? ` (BM25 #${m.bm25_rank}` : ""}{m.dense_rank ? `, dense #${m.dense_rank})` : m.bm25_rank ? ")" : ""}
                  </div>
                </Expander>
              </div>
            </div>
          </div>
        </Card>
      ))}
    </>
  );
}
