// Client-side "Download comparison" (DESIGN §8.5 Browser): built in memory and downloaded; nothing is stored.
import type { Canvas, Profile } from "./api";
import { money, range, stars } from "./format";

export const DISCLAIMER_TEXT =
  "This is an independent, free comparison tool. It is not a licensed insurance agent or broker and is not " +
  "affiliated with or endorsed by CMS, Medicare or any plan. It earns no commissions. Costs are estimates. " +
  "Confirm on Medicare Plan Finder (https://www.medicare.gov/plan-compare/), at 1-800-MEDICARE (1-800-633-4227), " +
  "or with your state's SHIP counselor (https://www.shiphelp.org/local-medicare-help, 1-877-839-2675).";

export function comparisonMarkdown(
  canvas: Canvas,
  profile: Profile | null,
  checklist: string[],
  planYear: number,
  now = new Date(),
): string {
  const rows = canvas.rows ?? [];
  const ranked = rows.filter((r) => r.rank !== null);
  const dropped = rows.filter((r) => r.rank === null);
  const out: string[] = [
    `# Medicare plan comparison, ${planYear}`,
    "",
    `Generated ${now.toISOString().slice(0, 10)}.`,
    "",
    `> ${DISCLAIMER_TEXT}`,
    "",
  ];
  if (profile?.county_name) out.push(`County: ${profile.county_name}, ${profile.state ?? ""}`, "");
  if (profile?.drugs.length) out.push(`Drugs: ${profile.drugs.map((d) => d.name).join(", ")}`, "");
  out.push(
    "| Rank | Plan | ID | Est. yearly cost | Premium/mo | Worst case | Stars | Drugs covered |",
    "|---|---|---|---|---|---|---|---|",
  );
  for (const r of ranked) {
    out.push(
      `| ${r.rank} | ${r.plan_name.replace(/\|/g, "/")} | ${r.plan_key} | ${range(r.total_low_cents, r.total_high_cents)} | ${money(r.monthly_premium_cents)} | ${money(r.worst_case_cents, { whole: true })} | ${stars(r.star_overall)} | ${r.drugs_covered}/${r.drugs_total} |`,
    );
  }
  if (dropped.length) {
    out.push("", "## Not ranked", "");
    for (const r of dropped) out.push(`- ${r.plan_name} (${r.plan_key}): ${r.dropped_reason}`);
  }
  if (canvas.notes?.length) {
    out.push("", "## How we estimate", "");
    for (const n of canvas.notes) out.push(`- ${n}`);
  }
  out.push("", "## Before you enroll", "");
  checklist.forEach((c, i) => out.push(`${i + 1}. ${c}`));
  out.push("");
  return out.join("\n");
}

export function download(name: string, text: string): void {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
