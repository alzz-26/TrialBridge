import { useState } from "react";
import { Check, ChevronDown, ChevronRight, CircleHelp, Minus, X } from "lucide-react";
import type { Criterion, Evaluation, Predicate, Verdict } from "./api";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

const VERDICT: Record<Verdict, { label: string; cls: string }> = {
  eligible: { label: "Eligible", cls: "bg-emerald-100 text-emerald-800 ring-emerald-600/20" },
  possibly_eligible: { label: "Possibly eligible", cls: "bg-amber-100 text-amber-800 ring-amber-600/20" },
  ineligible: { label: "Ineligible", cls: "bg-rose-100 text-rose-800 ring-rose-600/20" },
};

export function VerdictBadge({ v }: { v: Verdict }) {
  const s = VERDICT[v];
  return <span className={cx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset", s.cls)}>{s.label}</span>;
}

export function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>{children}</div>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
      {label}…
    </div>
  );
}

export function ScoreBar({ e }: { e: Evaluation }) {
  const w = (n: number) => `${(100 * n) / Math.max(e.total, 1)}%`;
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-slate-100" title={`${e.passed} pass · ${e.unknown} unknown · ${e.failed} fail`}>
      <div className="bg-emerald-500" style={{ width: w(e.passed) }} />
      <div className="bg-amber-400" style={{ width: w(e.unknown) }} />
      <div className="bg-rose-500" style={{ width: w(e.failed) }} />
    </div>
  );
}

const STATUS_ICON: Record<string, { icon: React.ReactNode; cls: string; label: string }> = {
  met: { icon: <Check size={14} />, cls: "bg-emerald-100 text-emerald-700", label: "met" },
  clear: { icon: <Check size={14} />, cls: "bg-emerald-100 text-emerald-700", label: "not excluded" },
  not_met: { icon: <X size={14} />, cls: "bg-rose-100 text-rose-700", label: "not met" },
  excluded: { icon: <X size={14} />, cls: "bg-rose-100 text-rose-700", label: "excluded" },
  unknown: { icon: <CircleHelp size={14} />, cls: "bg-amber-100 text-amber-700", label: "unknown" },
  covered: { icon: <Minus size={14} />, cls: "bg-slate-100 text-slate-500", label: "covered" },
};

const PRED_CLS: Record<string, string> = {
  age: "bg-violet-100 text-violet-800",
  sex: "bg-violet-100 text-violet-800",
  lab: "bg-sky-100 text-sky-800",
  condition: "bg-orange-100 text-orange-800",
  medication: "bg-teal-100 text-teal-800",
};

export function fmtPred(p: Predicate): string {
  const op = (o?: string) => ({ ">=": "≥", "<=": "≤", between: "∈" } as Record<string, string>)[o ?? ""] ?? o;
  const val = Array.isArray(p.value) ? `[${p.value[0]}, ${p.value[1]}]` : p.value;
  switch (p.type) {
    case "age":
      return `age ${op(p.op)} ${val}`;
    case "sex":
      return `sex = ${String(p.value).toLowerCase()}`;
    case "lab":
      return `${p.lab} ${op(p.op)} ${val}${p.unit ? " " + p.unit : ""}`;
    case "condition":
    case "medication":
      return `${p.negated ? "NOT " : ""}${p.label ?? p.concept}${p.within_days ? ` (≤ ${p.within_days}d)` : ""}${p.status === "active" ? " [active]" : ""}`;
    case "covered":
      return "covered by registry age";
    default:
      return (p as any).partial ? "+ unparsed remainder → LLM (Phase 2)" : "free text → LLM (Phase 2)";
  }
}

export function PredicateChip({ p }: { p: Predicate }) {
  return (
    <span className={cx("inline-flex items-center rounded-md px-1.5 py-0.5 font-mono text-[11px]", PRED_CLS[p.type] ?? "bg-slate-100 text-slate-500")}
      title={p.note ?? undefined}>
      {fmtPred(p)}
    </span>
  );
}

/** Criterion text with the spans that produced predicates highlighted. */
export function Highlighted({ c }: { c: Criterion }) {
  const spans = c.predicates.filter((p) => p.span).map((p) => ({ s: p.span![0], e: p.span![1], t: p.type }))
    .sort((a, b) => a.s - b.s);
  const out: React.ReactNode[] = [];
  let i = 0;
  spans.forEach((sp, n) => {
    if (sp.s < i) return;
    out.push(c.text.slice(i, sp.s));
    out.push(<mark key={n} className={cx("rounded px-0.5", PRED_CLS[sp.t])}>{c.text.slice(sp.s, sp.e)}</mark>);
    i = sp.e;
  });
  out.push(c.text.slice(i));
  return <span>{out}</span>;
}

export function CriteriaTable({ criteria, showStatus = true }: { criteria: Criterion[]; showStatus?: boolean }) {
  const groups: [string, Criterion[]][] = [
    ["Inclusion", criteria.filter((c) => c.kind === "inclusion")],
    ["Exclusion", criteria.filter((c) => c.kind === "exclusion")],
  ];
  return (
    <div className="space-y-4">
      {groups.map(([name, cs]) => cs.length > 0 && (
        <div key={name}>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">{name} criteria</div>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
            {cs.map((c, n) => {
              const st = c.status ? STATUS_ICON[c.status] : null;
              return (
                <li key={n} className="flex gap-3 px-3 py-2 text-sm">
                  {showStatus && st && (
                    <span title={st.label} className={cx("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full", st.cls)}>{st.icon}</span>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className={cx("leading-snug", c.structured && "italic text-slate-500")}><Highlighted c={c} /></div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {c.predicates.map((p, k) => <PredicateChip key={k} p={p} />)}
                    </div>
                    {showStatus && c.reasons && c.reasons.length > 0 && (
                      <div className="mt-1 text-xs text-slate-500">→ {c.reasons.join("; ")}</div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function Expander({ title, children, defaultOpen = false }: { title: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-1 text-left text-sm font-medium text-brand-600 hover:text-brand-700">
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        {title}
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <Card className="px-4 py-3">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-0.5 text-2xl font-semibold tabular-nums text-slate-900">{value}</div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
    </Card>
  );
}
