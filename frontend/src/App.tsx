import { useEffect, useState } from "react";
import { BarChart3, FileSearch, HeartPulse, Users } from "lucide-react";
import { api } from "./api";
import { cx } from "./components";
import Evaluation from "./pages/Evaluation";
import Parser from "./pages/Parser";
import PatientMatch from "./pages/PatientMatch";
import Recruiter from "./pages/Recruiter";

const TABS = [
  { id: "patient", label: "Patient → Trials", icon: HeartPulse, el: <PatientMatch /> },
  { id: "recruiter", label: "Trial → Patients", icon: Users, el: <Recruiter /> },
  { id: "parser", label: "Criteria Parser", icon: FileSearch, el: <Parser /> },
  { id: "eval", label: "Evaluation", icon: BarChart3, el: <Evaluation /> },
];

export default function App() {
  const [tab, setTab] = useState(() => location.hash.slice(1) || "patient");
  const [stats, setStats] = useState<any>(null);
  useEffect(() => { api.stats().then(setStats).catch(() => {}); }, []);
  useEffect(() => { location.hash = tab; }, [tab]);

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">TB</div>
            <div>
              <div className="font-semibold leading-tight">TrialBridge</div>
              <div className="text-[11px] leading-tight text-slate-500">Explainable clinical trial matching</div>
            </div>
          </div>
          <nav className="flex flex-wrap gap-1">
            {TABS.map((t) => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={cx("flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium",
                  tab === t.id ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100")}>
                <t.icon size={16} />{t.label}
              </button>
            ))}
          </nav>
          {stats && (
            <div className="ml-auto flex gap-4 text-xs text-slate-500">
              <span><b className="text-slate-800">{stats.trials.toLocaleString()}</b> trials</span>
              <span><b className="text-slate-800">{stats.criteria.toLocaleString()}</b> criteria</span>
              <span><b className="text-slate-800">{stats.patients}</b> patients</span>
              <span>{stats.dense_index ? "hybrid index" : "BM25 index"}</span>
            </div>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">{TABS.find((t) => t.id === tab)?.el}</main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-slate-400">
        Research prototype on synthetic (Synthea) patients. Not medical advice.
      </footer>
    </div>
  );
}
