import { comparisonCsv, csvCell } from "./exportCsv";
import { DISCLAIMER_TEXT } from "./exportMd";
import { plan, ROWS } from "./testdata";

/** Minimal CSV reader for the test (quoted fields with "" escapes). */
function parse(csv: string): string[][] {
  const out: string[][] = [];
  for (const line of csv
    .replace(/^\ufeff/, "")
    .trimEnd()
    .split("\r\n")) {
    const cells: string[] = [];
    let cur = "";
    let q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (q && ch === '"' && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else if (ch === '"') q = !q;
      else if (ch === "," && !q) {
        cells.push(cur);
        cur = "";
      } else cur += ch;
    }
    cells.push(cur);
    out.push(cells);
  }
  return out;
}

describe("download comparison as CSV", () => {
  const baseline = plan({
    plan_key: "ORIGINAL_MEDICARE",
    plan_name: "Original Medicare + Part D (standard)",
    is_baseline: true,
    pdp_plan_key: "S5617_001_0",
    rank: null,
    worst_case_cents: null,
    total_est_cents: 500000,
  });
  const rows = [
    ROWS[1],
    ROWS[2],
    { ...ROWS[0], plan_name: 'Plan, with "quotes"', delta_vs_baseline_cents: -177145 },
  ];
  const csv = comparisonCsv(
    { rows, baseline, notes: ["Part B is a placeholder."] },
    null,
    2027,
    new Date("2026-11-24T12:00:00Z"),
  );
  const t = parse(csv);
  const col = (name: string) => t[0].indexOf(name);

  it("starts with a BOM and one header row, then standard, ranked by rank, then not ranked", () => {
    expect(csv.startsWith("\ufeffRank,Plan,Plan ID,")).toBe(true);
    expect(t.slice(1, 5).map((r) => r[0])).toEqual(["Standard", "1", "2", "Not ranked"]);
    expect(t[4][col("Not ranked because")]).toBe("doesn't cover all your drugs");
  });

  it("writes amounts as plain dollar numbers so a spreadsheet can sort them", () => {
    const r = t[2];
    expect(r[col("Plan")]).toBe('Plan, with "quotes"');
    expect(r[col("Est. yearly cost ($)")]).toBe("3228.55");
    expect(r[col("Worst case/yr ($)")]).toBe("8984.80");
    expect(r[col("MOOP ($)")]).toBe("6550.00");
    expect(r[col("Part D deductible ($)")]).toBe("325.00");
    expect(r[col("Stars")]).toBe("4.5");
    expect(r[col("vs. standard/yr ($)")]).toBe("-1771.45");
    expect(t[1][col("Worst case/yr ($)")]).toBe("No limit");
    expect(t[1][col("Plan ID")]).toBe("S5617_001_0");
  });

  it("puts the disclaimer and notes below a blank row, outside the sortable block", () => {
    const blank = t.findIndex((r) => r.length === 1 && r[0] === "");
    expect(blank).toBe(5);
    const tail = t.slice(blank + 1).map((r) => r[0]);
    expect(tail[0]).toBe("Medicare plan comparison, 2027. Generated 2026-11-24.");
    expect(tail).toContain("Part B is a placeholder.");
    expect(tail).toContain(DISCLAIMER_TEXT);
  });

  it("neutralizes text a spreadsheet would run as a formula", () => {
    expect(csvCell("=HYPERLINK(1)")).toBe("'=HYPERLINK(1)");
    expect(csvCell("@x")).toBe("'@x");
    expect(csvCell("-cmd|x")).toBe("'-cmd|x");
    expect(csvCell("-1771.45")).toBe("-1771.45"); // a plain negative amount stays a number
    expect(csvCell(-3)).toBe("-3");
  });
});
