import { useState } from "react";
import { api, type Criterion } from "../api";
import { Card, CriteriaTable } from "../components";

const SAMPLE = `Inclusion Criteria:

* Adults aged 18 to 75 years with type 2 diabetes mellitus
* HbA1c between 7.0% and 10.5%
* eGFR > 45 mL/min/1.73m2
* On stable dose of metformin for at least 3 months

Exclusion Criteria:

* History of myocardial infarction, stroke or unstable angina within 6 months prior to screening
* Type 1 diabetes
* Pregnant or breastfeeding women
* ALT or AST > 3 x ULN
* Uncontrolled hypertension (SBP > 160 mmHg)
* Any condition that in the opinion of the investigator would interfere with participation`;

export default function Parser() {
  const [text, setText] = useState(SAMPLE);
  const [nct, setNct] = useState("");
  const [res, setRes] = useState<{ criteria: Criterion[]; stats: any } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function parse(t = text) {
    setErr(null);
    setRes(await api.parse(t));
  }
  async function load() {
    if (!nct.trim()) return;
    setErr(null);
    try {
      const t = await api.trial(nct.trim().toUpperCase());
      setText(t.eligibility);
      setRes({ criteria: t.criteria, stats: t.parse_stats });
    } catch {
      setErr(`${nct} is not in the local database`);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card className="p-4">
        <div className="mb-1 font-semibold">Criteria parser</div>
        <p className="mb-3 text-sm text-slate-500">
          Free-text eligibility → executable predicates. Highlighted spans show exactly which words produced each predicate.
        </p>
        <form onSubmit={(e) => { e.preventDefault(); load(); }} className="mb-2 flex gap-2">
          <input value={nct} onChange={(e) => setNct(e.target.value)} placeholder="Load trial by NCT id, e.g. NCT07442006"
            className="flex-1 rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm outline-none focus:border-brand-500" />
          <button type="submit" className="rounded-lg border border-slate-200 px-3 text-sm hover:bg-slate-50">Load</button>
        </form>
        {err && <div className="mb-2 text-sm text-rose-600">{err}</div>}
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={22}
          className="w-full rounded-lg border border-slate-200 p-3 font-mono text-xs outline-none focus:border-brand-500" />
        <button onClick={() => parse()} className="mt-2 w-full rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
          Parse criteria
        </button>
      </Card>
      <div className="space-y-4">
        {res && (
          <>
            <Card className="flex flex-wrap gap-6 p-4 text-sm">
              <div><div className="text-2xl font-semibold">{res.stats.criteria}</div><div className="text-slate-500">criteria</div></div>
              <div><div className="text-2xl font-semibold">{res.stats.parsed}</div><div className="text-slate-500">machine-readable</div></div>
              <div><div className="text-2xl font-semibold">{res.stats.coverage != null ? Math.round(res.stats.coverage * 100) + "%" : "–"}</div><div className="text-slate-500">coverage</div></div>
              <div className="flex flex-wrap items-center gap-1 text-xs">
                {Object.entries(res.stats.predicates as Record<string, number>).map(([k, v]) => (
                  <span key={k} className="rounded bg-slate-100 px-1.5 py-0.5">{k}: {v}</span>
                ))}
              </div>
            </Card>
            <Card className="p-4"><CriteriaTable criteria={res.criteria} showStatus={false} /></Card>
          </>
        )}
      </div>
    </div>
  );
}
