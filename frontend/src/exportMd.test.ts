import { comparisonMarkdown, DISCLAIMER_TEXT } from "./exportMd";
import { ROWS } from "./testdata";

describe("download comparison", () => {
  it("includes the disclaimer, ranked rows, dropped reasons and the checklist", () => {
    const md = comparisonMarkdown(
      { rows: ROWS, notes: ["Part B is a placeholder."] },
      {
        path: "both",
        drugs: [{ name: "metformin" }],
        providers: [],
        utilization: "medium",
        pharmacy_preference: "retail",
        must_haves: {},
        county_name: "Maricopa",
        state: "AZ",
      },
      ["Confirm in Plan Finder."],
      2027,
      new Date("2026-11-17T12:00:00Z"),
    );
    expect(md).toContain(DISCLAIMER_TEXT);
    expect(md).toContain("| 1 | Test Plan A (HMO) | H0028_028_0 | $3,229–$3,809 |");
    expect(md).toContain("Dropped Plan C (H2222_002_0): doesn't cover all your drugs");
    expect(md).toContain("1. Confirm in Plan Finder.");
    expect(md).toContain("Generated 2026-11-17");
  });
});
