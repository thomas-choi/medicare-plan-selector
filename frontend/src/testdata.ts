import type { AppConfig, PlanRow } from "./api";

export const CONFIG: AppConfig = {
  plan_year: 2027,
  default_mode: "nosave",
  modes: ["nosave", "saved"],
  consent_version: "2026-11-17",
  retention_days: 30,
  feedback_retention_days: 365,
  ephemeral_idle_minutes: 30,
  ephemeral_max_hours: 4,
  llm_enabled: true,
  llm_provider_label: "Anthropic Claude (claude-test)",
  limits: { message_chars: 2000, drugs: 30, providers: 15 },
  estimate_disclaimer: "These are estimates.",
  checklist: ["Confirm in Medicare Plan Finder.", "Call each plan about your doctors."],
  glossary: [
    { id: "est_yearly_cost", title: "Est. yearly cost", text: "What a typical year could cost you." },
    { id: "worst_case", title: "Worst case", text: "What a very bad year could cost." },
  ],
  app_version: "test",
};

export function plan(over: Partial<PlanRow> = {}): PlanRow {
  return {
    plan_key: "H0028_028_0",
    plan_name: "Test Plan A (HMO)",
    organization: "Org A",
    category: "MA-PD",
    plan_type: "HMO",
    path: "ma",
    star_overall: 4.5,
    monthly_premium_cents: 0,
    premium_annual_cents: 0,
    part_b_annual_cents: 243480,
    part_d_deductible_cents: 32500,
    moop_cents: 655000,
    drug_low_cents: 47375,
    drug_high_cents: 47375,
    medical_low_cents: 32000,
    medical_high_cents: 90000,
    total_low_cents: 322855,
    total_high_cents: 380855,
    total_est_cents: 322855,
    worst_case_cents: 898480,
    drugs_covered: 2,
    drugs_total: 2,
    drugs: [
      {
        name: "metformin",
        covered: true,
        tier: 1,
        restrictions: [],
        annual_low_cents: 0,
        annual_high_cents: 0,
        notes: [],
      },
    ],
    dropped_reason: null,
    rank: 1,
    notes: [],
    ...over,
  };
}

export const ROWS: PlanRow[] = [
  plan(),
  plan({
    plan_key: "H1111_001_0",
    plan_name: "Test Plan B (PPO)",
    rank: 2,
    total_est_cents: 400000,
    total_low_cents: 400000,
    total_high_cents: 450000,
    star_overall: 3.5,
    monthly_premium_cents: 2500,
  }),
  plan({
    plan_key: "H2222_002_0",
    plan_name: "Dropped Plan C",
    rank: null,
    dropped_reason: "doesn't cover all your drugs",
    drugs_covered: 1,
  }),
];

type Handler = (url: string, init?: RequestInit) => unknown;

/** A fetch mock routed by "METHOD /path" (query string ignored). Records calls. */
export function mockFetch(routes: Record<string, Handler | unknown>) {
  const calls: { key: string; body: unknown }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const key = `${(init?.method ?? "GET").toUpperCase()} ${url.split("?")[0]}`;
    calls.push({ key, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (!(key in routes)) return new Response(JSON.stringify({ detail: { code: "nf" } }), { status: 404 });
    const r = routes[key];
    const val = typeof r === "function" ? (r as Handler)(url, init) : r;
    if (val instanceof Response) return val;
    return new Response(JSON.stringify(val), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

/** The pinned "Original Medicare + Part D (standard)" row (addendum A5). */
export const BASELINE: PlanRow = plan({
  plan_key: "BASELINE",
  plan_name: "Original Medicare + Part D (standard)",
  organization: "Original Medicare + PDP Org",
  category: "BASELINE",
  plan_type: "Original Medicare + PDP",
  path: "original",
  star_overall: null,
  monthly_premium_cents: 600,
  premium_annual_cents: 7200,
  moop_cents: null,
  worst_case_cents: null,
  total_low_cents: 500000,
  total_high_cents: 520000,
  total_est_cents: 510000,
  rank: null,
  is_baseline: true,
  pinned: true,
  pdp_plan_key: "S4802_134_0",
  pdp_plan_name: "Test PDP (PDP)",
  part_b_deductible_cents: 29200,
  components: [
    { kind: "part_a", label: "Part A (hospital)", monthly_cents: 0, annual_cents: 0 },
    { kind: "part_b", label: "Part B (medical)", monthly_cents: 20940, annual_cents: 251280 },
    { kind: "pdp", label: "Test PDP (PDP)", plan_key: "S4802_134_0", monthly_cents: 600, annual_cents: 7200 },
  ],
  medigap: { plan: null, premium_included: false, rule_note: "No Medigap: no yearly out-of-pocket limit." },
  notes: ["Part A premium assumed $0."],
});

/** Plan rows with their difference to BASELINE (total_est − 510000). */
export const ROWS_VS_BASELINE: PlanRow[] = ROWS.map((r) => ({
  ...r,
  delta_vs_baseline_cents: r.total_est_cents - 510000,
}));
