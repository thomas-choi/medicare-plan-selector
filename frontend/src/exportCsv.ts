// Client-side "Download comparison" as CSV (DESIGN §8.5 Browser): built in memory and downloaded; nothing is stored.
// One row per plan with plain numbers (dollars, no "$" or thousands separators) so a spreadsheet can sort them.
// The disclaimer and notes follow after a blank row, outside the sortable block.
import type { Canvas, PlanRow, Profile } from "./api";
import { doctorSummary } from "./format";
import { DISCLAIMER_TEXT } from "./exportMd";

const HEADER = [
  "Rank",
  "Plan",
  "Plan ID",
  "Organization",
  "Plan type",
  "Est. yearly cost ($)",
  "Est. yearly low ($)",
  "Est. yearly high ($)",
  "Premium/mo ($)",
  "Premium/yr ($)",
  "Part B premium/yr ($)",
  "Drug cost low/yr ($)",
  "Drug cost high/yr ($)",
  "Medical low/yr ($)",
  "Medical high/yr ($)",
  "Worst case/yr ($)",
  "MOOP ($)",
  "Part D deductible ($)",
  "Stars",
  "Drugs covered",
  "Drugs entered",
  "Dental",
  "Your doctors",
  "vs. standard/yr ($)",
  "Not ranked because",
];

type Cell = string | number | null | undefined;

/** Dollars with cents as a plain number ("4016.55"); blank when unknown. */
function dollars(cents: number | null | undefined): Cell {
  return cents === null || cents === undefined ? "" : (cents / 100).toFixed(2);
}

/** RFC 4180 quoting, and text that a spreadsheet would run as a formula is prefixed with "'". A plain number such as
 * "-1771.45" is left alone so it still sorts as a number. */
export function csvCell(v: Cell): string {
  if (v === null || v === undefined) return "";
  let s = String(v);
  if (/^[=+\-@\t\r]/.test(s) && !/^-?\d+(\.\d+)?$/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function planCells(r: PlanRow, rank: Cell, delta: Cell): Cell[] {
  return [
    rank,
    r.plan_name,
    r.is_baseline ? (r.pdp_plan_key ?? "") : r.plan_key,
    r.is_baseline ? "" : r.organization,
    r.is_baseline ? "Original Medicare + drug plan" : (r.plan_type ?? r.category),
    dollars(r.total_est_cents),
    dollars(r.total_low_cents),
    dollars(r.total_high_cents),
    dollars(r.monthly_premium_cents),
    dollars(r.premium_annual_cents),
    dollars(r.part_b_annual_cents),
    dollars(r.drug_low_cents),
    dollars(r.drug_high_cents),
    dollars(r.medical_low_cents),
    dollars(r.medical_high_cents),
    r.worst_case_cents === null && r.is_baseline ? "No limit" : dollars(r.worst_case_cents),
    dollars(r.moop_cents),
    dollars(r.part_d_deductible_cents),
    r.star_overall ?? "",
    r.drugs_covered,
    r.drugs_total,
    r.dental?.summary ?? (r.is_baseline ? "No routine dental" : "No dental benefit listed"),
    doctorSummary(r.doctors, { original: r.is_baseline || r.path === "original" }),
    delta,
    r.dropped_reason ?? "",
  ];
}

export function comparisonCsv(
  canvas: Canvas,
  profile: Profile | null,
  planYear: number,
  now = new Date(),
): string {
  const rows = canvas.rows ?? [];
  const ranked = rows.filter((r) => r.rank !== null).sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));
  const dropped = rows.filter((r) => r.rank === null);
  const b = canvas.baseline;
  const lines: Cell[][] = [HEADER];
  if (b) lines.push(planCells(b, "Standard", ""));
  for (const r of ranked) lines.push(planCells(r, r.rank, b ? dollars(r.delta_vs_baseline_cents) : ""));
  for (const r of dropped)
    lines.push(planCells(r, "Not ranked", b ? dollars(r.delta_vs_baseline_cents) : ""));
  lines.push([]);
  lines.push([`Medicare plan comparison, ${planYear}. Generated ${now.toISOString().slice(0, 10)}.`]);
  if (profile?.county_name) lines.push([`County: ${profile.county_name}, ${profile.state ?? ""}`]);
  if (profile?.drugs.length) lines.push([`Drugs: ${profile.drugs.map((d) => d.name).join(", ")}`]);
  lines.push([
    "Amounts are US dollars per year unless the column says /mo. Est. yearly cost is the midpoint of low and high.",
  ]);
  lines.push(["vs. standard: negative = less than the standard Original Medicare + Part D option."]);
  for (const n of canvas.notes ?? []) lines.push([n]);
  lines.push([DISCLAIMER_TEXT]);
  // BOM so Excel reads UTF-8 ("–", "★", accented names) correctly.
  return "\ufeff" + lines.map((l) => l.map(csvCell).join(",")).join("\r\n") + "\r\n";
}
