// Thin client for the FastAPI backend. Cookies are HttpOnly; the SPA never stores anything in browser storage.

export type Mode = "nosave" | "saved";

export interface AppConfig {
  plan_year: number;
  default_mode: Mode;
  modes: Mode[];
  consent_version: string;
  retention_days: number;
  feedback_retention_days: number;
  ephemeral_idle_minutes: number;
  ephemeral_max_hours: number;
  llm_enabled: boolean;
  llm_provider_label: string | null;
  limits: { message_chars: number; drugs: number; providers: number };
  estimate_disclaimer: string;
  checklist: string[];
  glossary: GlossaryTerm[];
  app_version: string;
}

/** Meaning of a comparison column or term (GET /api/config; same text the assistant uses). */
export interface GlossaryTerm {
  id: string;
  title: string;
  text: string;
}

export interface Drug {
  name: string;
  rxcui?: string | null;
  days_supply?: 30 | 60 | 90;
  pharmacy?: Pharmacy;
  price_per_fill_cents?: number | null;
}
export type Pharmacy = "retail" | "pref_retail" | "mail" | "pref_mail";

export interface Profile {
  zip?: string | null;
  county_ssa?: string | null;
  county_name?: string | null;
  state?: string | null;
  path: "ma" | "original" | "both";
  drugs: Drug[];
  providers: Provider[];
  utilization: "low" | "medium" | "high";
  pharmacy_preference: Pharmacy;
  must_haves: {
    all_drugs_covered?: boolean;
    plan_types?: string[];
    min_stars?: number | null;
    max_moop_cents?: number | null;
    max_monthly_premium_cents?: number | null;
    dental?: boolean;
    dental_min_max_cents?: number | null;
    doctors_listed?: boolean;
  };
  weights?: {
    total_cost?: number;
    worst_case?: number;
    stars?: number;
    must_have_fit?: number;
    doctor_fit?: number;
  };
  medigap?: { plan: "G" | "N" | "HDG" | null; monthly_premium_cents?: number | null };
  snp_eligible?: boolean;
  current_plan_key?: string | null;
}

/** A doctor: free-text name, or picked from the NPI registry (then `npi` is set). */
export interface Provider {
  name: string;
  npi?: string | null;
  must_keep?: boolean;
  specialty?: string | null;
  city?: string | null;
}

export const emptyProfile = (): Profile => ({
  path: "both",
  drugs: [],
  providers: [],
  utilization: "medium",
  pharmacy_preference: "retail",
  must_haves: {},
});

/** GET /api/drugs. `matched_as` is set when the server fell back to the ingredient name or a closest match. */
export interface DrugSearch {
  candidates: { rxcui: string; name: string; tty?: string }[];
  matched_as?: string | null;
  how?: "exact" | "ingredient" | "approximate" | "none";
}

export interface DrugRow {
  name: string;
  covered: boolean;
  tier: number | null;
  restrictions: string[];
  annual_low_cents: number;
  annual_high_cents: number;
  notes: string[];
}

/** Plan dental benefits from the CMS PBP file b16 (addendum A4). `null` on a row = no dental benefit listed. */
export interface Dental {
  summary: string;
  has_preventive: boolean;
  has_comprehensive: boolean;
  max_cents: number | null;
  max_period: string | null;
  max_shared: boolean | null;
  optional_supplemental: boolean;
  services?: {
    code: string;
    label: string;
    group: "preventive" | "comprehensive" | "medicare_covered";
    cost: string;
    limit_text: string | null;
  }[];
  src_ref?: Record<string, unknown>;
}

/** A doctor's directory listing status for one plan (addendum A3.3). */
export interface DoctorStatus {
  npi: string;
  name: string;
  must_keep?: boolean;
  status: "listed" | "not_listed" | "unknown" | "unavailable" | "original_medicare" | "opted_out" | "no_npi";
  text: string;
  checked_at: string | null;
}

export interface BaselineComponent {
  kind: "part_a" | "part_b" | "pdp" | "medigap";
  label: string;
  plan_key?: string;
  monthly_cents: number | null;
  annual_cents: number | null;
}

export interface PlanRow {
  plan_key: string;
  plan_name: string;
  organization: string;
  category: string;
  plan_type: string | null;
  path: string;
  star_overall: number | null;
  monthly_premium_cents: number;
  premium_annual_cents: number;
  part_b_annual_cents: number;
  part_d_deductible_cents: number | null;
  moop_cents: number | null;
  drug_low_cents: number;
  drug_high_cents: number;
  medical_low_cents: number;
  medical_high_cents: number;
  total_low_cents: number;
  total_high_cents: number;
  total_est_cents: number;
  worst_case_cents: number | null;
  drugs_covered: number;
  drugs_total: number;
  drugs: DrugRow[];
  dropped_reason: string | null;
  rank: number | null;
  notes: string[];
  delta_vs_baseline_cents?: number | null;
  dental?: Dental | null;
  doctors?: DoctorStatus[];
  // Only on the pinned baseline row (canvas.baseline):
  is_baseline?: boolean;
  pinned?: boolean;
  pdp_plan_key?: string | null;
  pdp_plan_name?: string | null;
  part_b_deductible_cents?: number;
  part_a_deductible_cents?: number;
  components?: BaselineComponent[];
  medigap?: { plan: string | null; premium_included: boolean; rule_note: string };
}

export interface Canvas {
  tab?: "table" | "chart" | "side_by_side" | "checklist";
  rows?: PlanRow[];
  baseline?: PlanRow;
  top?: string[];
  selected?: string[];
  notes?: string[];
  recommendation_ids?: Record<string, string>;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Record<string, unknown>[];
}

export interface SessionView {
  session: { mode: Mode; expires_at: string; plan_year: number } | null;
  profile?: Profile | null;
  chat?: ChatMessage[];
  canvas?: Canvas;
  renewed?: boolean;
  expired?: boolean;
}

export interface County {
  ssa_code: string;
  fips: string | null;
  state: string | null;
  county: string;
  res_ratio: number | null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let code = "error";
    let message = `Request failed (${res.status}).`;
    try {
      const j = await res.json();
      const d = j.detail;
      if (d && typeof d === "object") {
        code = d.code ?? code;
        message = d.message ?? (d.errors ? "Please check the highlighted fields." : message);
      }
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  config: () => call<AppConfig>("GET", "/api/config"),
  session: () => call<SessionView>("GET", "/api/session"),
  start: (mode: Mode, consent_version: string, consent_feedback_phi = false) =>
    call<SessionView>("POST", "/api/session", {
      mode,
      consent_version,
      accept_terms: true,
      consent_feedback_phi,
    }),
  erase: () => call<{ deleted: boolean }>("DELETE", "/api/session"),
  saveProfile: (p: Profile) => call<{ profile: Profile }>("PUT", "/api/profile", p),
  location: (zip: string) =>
    call<{ counties: County[]; note: string | null }>("GET", `/api/location?zip=${encodeURIComponent(zip)}`),
  counties: (state: string) =>
    call<{ counties: County[] }>("GET", `/api/counties?state=${encodeURIComponent(state)}`),
  drugs: (q: string) => call<DrugSearch>("GET", `/api/drugs?q=${encodeURIComponent(q)}`),
  providers: (lastName: string, firstName: string, state: string) =>
    call<{
      candidates: { npi: string; name: string; specialty: string; city: string; state: string }[];
      note: string;
    }>(
      "GET",
      `/api/providers?last_name=${encodeURIComponent(lastName)}&first_name=${encodeURIComponent(firstName)}&state=${encodeURIComponent(state)}`,
    ),
  compare: (profile?: Profile) =>
    call<{
      canvas: Canvas;
      top: PlanRow[];
      checklist: string[];
      approximation_notes: string[];
      data_vintage: string;
      recommendation_ids: string[];
    }>("POST", "/api/compare", profile ? { profile } : {}),
  dental: (planKey: string) =>
    call<{ plan_key: string; dental: Dental; note: string }>(
      "GET",
      `/api/plans/${encodeURIComponent(planKey)}/benefits?category=dental`,
    ),
  feedback: (body: Record<string, unknown>) =>
    call<{ stored: string; linked: boolean }>("POST", "/api/feedback", body),
};

/** Best-effort "tab closed" signal (DESIGN §8.5 wipe trigger 4). */
export function beaconEnd(): void {
  if (typeof navigator !== "undefined" && "sendBeacon" in navigator) {
    navigator.sendBeacon("/api/session/end");
  }
}

export interface ChatEvents {
  onMeta?: (m: Record<string, unknown>) => void;
  onDelta: (text: string) => void;
  onCanvas?: (c: Canvas) => void;
  onProfile?: (p: Profile) => void;
  onDone?: (d: { citations: Record<string, unknown>[]; recommendation_ids: string[] }) => void;
}

/** Parse a complete or partial SSE buffer. Returns parsed events and the unconsumed tail. */
export function parseSse(buffer: string): { events: { event: string; data: string }[]; rest: string } {
  const events: { event: string; data: string }[] = [];
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7);
      else if (line.startsWith("data: ")) data.push(line.slice(6));
    }
    if (data.length) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

export async function sendChat(message: string, ev: ChatEvents): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok || !res.body) {
    let code = "error";
    let msg = "The assistant is unavailable right now. Use the form to compare plans.";
    try {
      const j = await res.json();
      code = j.detail?.code ?? code;
      msg = j.detail?.message ?? msg;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, code, msg);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const { events, rest } = parseSse(buf);
    buf = rest;
    for (const e of events) {
      const d = JSON.parse(e.data);
      if (e.event === "delta") ev.onDelta(d.text);
      else if (e.event === "meta") ev.onMeta?.(d);
      else if (e.event === "canvas") ev.onCanvas?.(d);
      else if (e.event === "profile") ev.onProfile?.(d);
      else if (e.event === "done") ev.onDone?.(d);
    }
  }
}
