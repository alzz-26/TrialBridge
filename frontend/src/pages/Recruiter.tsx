import { useEffect, useState } from "react";
import { Search, Users } from "lucide-react";
import { api, type PatientMatch, type TrialCard, type Verdict } from "../api";
import { Card, CriteriaTable, Expander, ScoreBar, Spinner, VerdictBadge, cx } from "../components";

export default function Recruiter() {
  const [q, setQ] = useState("type 2 diabetes");
  const [trials, setTrials] = useState<TrialCard[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [res, setRes] = useState<{ trial: TrialCard; cohort_size: number; counts: Record<Verdict, number>; results: PatientMatch[] } | null>(null);
  const [loading, setLoading] = useState(false);

  const [searching, setSearching] = useState(false);

  async function search() {
    setSearching(true);
    try {
      setTrials((await api.trials(q, 30)).results);
    } finally {
      setSearching(false);
    }
  }

  useEffect(() => { search(); }, []); // show trials for the default query on first load

  async function pick(id: string) {
    setSel(id);
    setLoading(true);
    try {
      setRes(await api.matchTrial(id, 100));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[400px_1fr]">
      <Card className="p-4">
        <div className="mb-1 font-semibold">Recruiter view</div>
        <p className="mb-3 text-sm text-slate-500">Pick a trial and screen the whole synthetic cohort against its parsed criteria.</p>
        <form onSubmit={(e) => { e.preventDefault(); search(); }} className="mb-2 flex gap-2">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-2.5 top-2.5 text-slate-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search trials (BM25)"
              className="w-full rounded-lg border border-slate-200 py-2 pl-8 pr-3 text-sm outline-none focus:border-brand-500" />
          </div>
          <button type="submit" disabled={searching}
            className="rounded-lg bg-brand-600 px-3 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60">
            {searching ? "Searching..." : "Search"}
          </button>
        </form>
        <ul className="max-h-[560px] divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
          {trials.map((t) => (
            <li key={t.trial_id}>
              <button onClick={() => pick(t.trial_id)} className={cx("w-full px-3 py-2 text-left text-sm hover:bg-slate-50", sel === t.trial_id && "bg-brand-50")}>
                <div className="font-mono text-xs text-brand-600">{t.trial_id}</div>
                <div className="line-clamp-2 leading-snug">{t.title}</div>
              </button>
            </li>
          ))}
          {trials.length === 0 && <li className="p-4 text-center text-sm text-slate-400">{searching ? "Searching..." : "No trials found - try another search"}</li>}
        </ul>
      </Card>

      <div className="min-w-0 space-y-4">
        {loading && <Spinner label="Screening cohort" />}
        {!loading && !res && (
          <Card className="flex flex-col items-center p-12 text-center text-slate-500">
            <Users size={36} className="mb-3 text-slate-300" />
            Select a trial to see its eligible candidates.
          </Card>
        )}
        {!loading && res && (
          <>
            <Card className="p-4">
              <div className="font-mono text-xs text-brand-600">{res.trial.trial_id}</div>
              <div className="text-lg font-semibold leading-snug">{res.trial.title}</div>
              <div className="mt-3 grid grid-cols-3 gap-3 text-center">
                <div className="rounded-lg bg-emerald-50 p-3"><div className="text-2xl font-semibold text-emerald-700">{res.counts.eligible}</div><div className="text-xs text-emerald-700">eligible</div></div>
                <div className="rounded-lg bg-amber-50 p-3"><div className="text-2xl font-semibold text-amber-700">{res.counts.possibly_eligible}</div><div className="text-xs text-amber-700">possibly eligible</div></div>
                <div className="rounded-lg bg-rose-50 p-3"><div className="text-2xl font-semibold text-rose-700">{res.counts.ineligible}</div><div className="text-xs text-rose-700">ineligible</div></div>
              </div>
              <div className="mt-2 text-xs text-slate-400">cohort of {res.cohort_size} synthetic patients</div>
            </Card>
            {res.results.filter((r) => r.verdict !== "ineligible").slice(0, 30).map((r) => (
              <Card key={r.patient_id} className="p-4">
                <div className="flex items-center gap-2">
                  <VerdictBadge v={r.verdict} />
                  <span className="font-medium">{r.name}</span>
                  <span className="text-sm text-slate-500">{Math.round(r.age)} y · {r.sex?.toLowerCase()}</span>
                </div>
                <div className="mt-2 grid grid-cols-[1fr_auto] items-center gap-3">
                  <ScoreBar e={r} />
                  <span className="text-xs text-slate-500">{r.passed}✓ {r.unknown}? {r.failed}✗</span>
                </div>
                <div className="mt-2"><Expander title="Criteria breakdown"><CriteriaTable criteria={r.criteria} /></Expander></div>
              </Card>
            ))}
            {res.results.every((r) => r.verdict === "ineligible") && (
              <Card className="p-4 text-sm text-slate-500">No candidates in the current cohort pass this trial's criteria.</Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}
