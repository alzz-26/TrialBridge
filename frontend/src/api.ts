export type Predicate = {
  type: "age" | "sex" | "lab" | "condition" | "medication" | "unparsed" | "covered";
  op?: string;
  value?: number | [number, number] | string;
  lab?: string;
  unit?: string;
  concept?: string;
  label?: string;
  negated?: boolean;
  within_days?: number;
  status?: string;
  note?: string | null;
  span?: [number, number];
};

export type Criterion = {
  kind: "inclusion" | "exclusion";
  text: string;
  predicates: Predicate[];
  structured?: boolean;
  status?: "met" | "not_met" | "unknown" | "clear" | "excluded" | "covered";
  reasons?: string[];
};

export type Verdict = "eligible" | "possibly_eligible" | "ineligible";

export type Evaluation = {
  verdict: Verdict;
  score: number;
  passed: number;
  failed: number;
  unknown: number;
  total: number;
  criteria: Criterion[];
};

export type TrialCard = {
  trial_id: string;
  source: string;
  title: string;
  status: string;
  phase: string | null;
  conditions: string[];
  interventions: string[];
  min_age_years: number | null;
  max_age_years: number | null;
  sex: string;
  countries: string[];
  summary: string;
};

export type TrialMatch = Evaluation & {
  trial: TrialCard;
  retrieval_rank: number;
  retrieval_score: number;
  final_score: number;
  bm25_rank?: number;
  dense_rank?: number;
};

export type PatientBrief = { patient_id: string; name: string; age: number; sex: string; conditions: string[] };

export type Profile = {
  patient_id: string;
  name: string;
  age: number | null;
  sex: string | null;
  conditions: { concept: string | null; display: string; onset?: string | null; active?: boolean }[];
  medications: { concept: string | null; display: string; start?: string | null; active?: boolean }[];
  labs: Record<string, { value: number; unit?: string; date?: string | null }>;
  negated?: string[];
  summary: string;
};

export type PatientMatch = Evaluation & { patient_id: string; name: string; age: number; sex: string };

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const api = {
  stats: () => j<any>("/api/stats"),
  vocab: () => j<{ conditions: { key: string; label: string }[]; medications: { key: string; label: string }[]; labs: { key: string; label: string; unit: string }[] }>("/api/vocab"),
  patients: (condition?: string) =>
    j<{ total: number; results: PatientBrief[] }>(`/api/patients${condition ? `?condition=${encodeURIComponent(condition)}` : ""}`),
  patient: (id: string) => j<Profile>(`/api/patients/${id}`),
  trials: (q: string, limit = 25) => j<{ total: number; results: TrialCard[] }>(`/api/trials?q=${encodeURIComponent(q)}&limit=${limit}`),
  trial: (id: string) => j<TrialCard & { eligibility: string; criteria: Criterion[]; parse_stats: any }>(`/api/trials/${id}`),
  matchPatient: (body: object) =>
    j<{ profile: Profile; query: string; results: TrialMatch[] }>("/api/match/patient", { method: "POST", body: JSON.stringify(body) }),
  matchTrial: (id: string, k = 100) =>
    j<{ trial: TrialCard; cohort_size: number; counts: Record<Verdict, number>; results: PatientMatch[] }>(`/api/match/trial/${id}?k=${k}`),
  parse: (text: string) => j<{ criteria: Criterion[]; stats: any }>("/api/parse", { method: "POST", body: JSON.stringify({ text }) }),
  evaluation: () => j<Record<string, any>>("/api/eval"),
};
