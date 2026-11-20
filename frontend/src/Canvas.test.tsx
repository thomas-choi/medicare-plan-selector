import { fireEvent, render, screen, within } from "@testing-library/react";
import { Canvas, CostChart, PlanTable, SideBySide } from "./Canvas";
import { ROWS } from "./testdata";

describe("canvas", () => {
  it("greys out dropped plans with the reason, after ranked ones", () => {
    render(<PlanTable rows={ROWS} selected={[]} onSelect={() => {}} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[2]).toHaveClass("dropped");
    expect(within(rows[2]).getByText(/Not ranked: doesn't cover all your drugs/)).toBeInTheDocument();
  });

  it("sorts by column", () => {
    render(<PlanTable rows={ROWS} selected={[]} onSelect={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Stars" }));
    const first = screen.getAllByRole("row")[1];
    expect(first).toHaveTextContent("Test Plan A");
    fireEvent.click(screen.getByRole("button", { name: "Premium/mo" }));
    fireEvent.click(screen.getByRole("button", { name: "Premium/mo" }));
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("Test Plan B");
  });

  it("charts stacked bars with a worst-case marker", () => {
    const { container } = render(<CostChart rows={ROWS.slice(0, 2)} />);
    expect(container.querySelectorAll("rect")).toHaveLength(6);
    expect(container.querySelectorAll("line.worst")).toHaveLength(2);
  });

  it("side-by-side shows 2–5 plans", () => {
    render(<SideBySide rows={[]} fallback={ROWS.slice(0, 2)} />);
    expect(screen.getByRole("columnheader", { name: "Test Plan B (PPO)" })).toBeInTheDocument();
    expect(screen.getAllByText("$6,550")).toHaveLength(2);
  });

  it("shows top-3 cards with feedback buttons and the checklist tab", () => {
    const onTab = vi.fn();
    render(
      <Canvas
        canvas={{ rows: ROWS }}
        checklist={["Call each plan."]}
        estimateDisclaimer="Estimates only."
        tab="checklist"
        onTab={onTab}
        selected={[]}
        onSelect={() => {}}
      />,
    );
    expect(screen.getAllByRole("button", { name: "Helpful" })).toHaveLength(2);
    expect(screen.getByText("Call each plan.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Cost chart" }));
    expect(onTab).toHaveBeenCalledWith("chart");
  });
});

describe("standard Original Medicare + Part D baseline (B8)", () => {
  it("is the first row with the Standard badge and stays first when sorting", async () => {
    const { BASELINE, ROWS_VS_BASELINE } = await import("./testdata");
    render(<PlanTable rows={ROWS_VS_BASELINE} baseline={BASELINE} selected={[]} onSelect={() => {}} />);
    const first = () => screen.getAllByRole("row")[1];
    expect(first()).toHaveClass("baseline");
    expect(within(first()).getByText("Standard")).toBeInTheDocument();
    expect(first()).toHaveTextContent("Part A + Part B + drug plan Test PDP (PDP)");
    expect(within(first()).getByText("No limit")).toBeInTheDocument();
    expect(screen.getAllByRole("row")[2]).toHaveTextContent("$1,871 less"); // 322855 − 510000, rounded
    for (const col of ["Est. yearly cost", "Premium/mo", "Worst case", "Stars", "Rank"]) {
      fireEvent.click(screen.getByRole("button", { name: col }));
      expect(first()).toHaveClass("baseline");
      fireEvent.click(screen.getByRole("button", { name: col }));
      expect(first()).toHaveClass("baseline");
    }
  });

  it("is always the first side-by-side column", async () => {
    const { BASELINE, ROWS_VS_BASELINE } = await import("./testdata");
    render(
      <SideBySide rows={[ROWS_VS_BASELINE[1]]} fallback={ROWS_VS_BASELINE.slice(0, 2)} baseline={BASELINE} />,
    );
    const heads = screen.getAllByRole("columnheader").slice(1);
    expect(heads[0]).toHaveTextContent("Standard Original Medicare + Part D (standard)");
    expect(heads).toHaveLength(3);
    expect(screen.getByText("Part B $292 + drugs $325.00")).toBeInTheDocument();
    expect(screen.getAllByText("No limit")).toHaveLength(2); // out-of-pocket cap and worst case
  });

  it("is in the downloaded comparison", async () => {
    const { BASELINE, ROWS_VS_BASELINE } = await import("./testdata");
    const { comparisonMarkdown } = await import("./exportMd");
    const md = comparisonMarkdown({ rows: ROWS_VS_BASELINE, baseline: BASELINE }, null, [], 2027);
    const lines = md.split("\n");
    const head = lines.findIndex((l) => l.startsWith("| Rank |"));
    expect(lines[head + 2]).toMatch(
      /^\| Standard \| Original Medicare \+ Part D \(standard\) \| drug plan S4802_134_0/,
    );
    expect(lines[head + 3]).toMatch(/\| \$1,871 less \|$/);
    expect(md).toContain("- Part B (medical): $209.40/month");
  });
});

describe("dental (WP12)", () => {
  afterEach(() => vi.unstubAllGlobals());
  const golden = {
    summary: "Preventive $0 · Comprehensive 0–50% · Max $500/yr (shared)",
    has_preventive: true,
    has_comprehensive: true,
    max_cents: 50000,
    max_period: "year",
    max_shared: true,
    optional_supplemental: false,
  };

  it("shows the dental summary per row; the standard row and PDPs have no routine dental", async () => {
    const { BASELINE, ROWS_VS_BASELINE } = await import("./testdata");
    const rows = [{ ...ROWS_VS_BASELINE[0], dental: golden }, ROWS_VS_BASELINE[1]];
    const base = {
      ...BASELINE,
      dental: {
        ...golden,
        summary: "No routine dental (Original Medicare and Medigap don't cover it)",
        has_preventive: false,
        has_comprehensive: false,
      },
    };
    render(<PlanTable rows={rows} baseline={base} selected={[]} onSelect={() => {}} />);
    const r = screen.getAllByRole("row");
    expect(within(r[1]).getByText(/^No routine dental/)).toBeInTheDocument();
    expect(within(r[2]).getByText(golden.summary)).toBeInTheDocument();
    expect(within(r[3]).getByText("No dental benefit listed")).toBeInTheDocument();
  });

  it("side-by-side loads per-service dental costs from the benefits endpoint", async () => {
    const { ROWS_VS_BASELINE, mockFetch } = await import("./testdata");
    const calls = mockFetch({
      "GET /api/plans/H0028_028_0/benefits": {
        plan_key: "H0028_028_0",
        note: "",
        dental: {
          ...golden,
          services: [
            { code: "pc", label: "Cleanings", group: "preventive", cost: "$0", limit_text: "2 per year" },
            {
              code: "prm",
              label: "Dentures (removable prosthodontics)",
              group: "comprehensive",
              cost: "50%",
              limit_text: null,
            },
          ],
        },
      },
    });
    const rows = [{ ...ROWS_VS_BASELINE[0], dental: golden }, ROWS_VS_BASELINE[1]];
    render(<SideBySide rows={rows} fallback={rows} />);
    expect(screen.getByText(golden.summary)).toBeInTheDocument();
    expect(await screen.findByText("Dentures (removable prosthodontics): 50%")).toBeInTheDocument();
    expect(screen.getByText("Cleanings: $0")).toBeInTheDocument();
    expect(screen.getByText("2 per year")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toEqual(["GET /api/plans/H0028_028_0/benefits"]); // no call for plan B
  });
});

describe("doctor listing badges (WP13)", () => {
  const doc = (name: string, status: string, text: string) => ({
    npi: "1234567893",
    name,
    must_keep: true,
    status: status as "listed",
    text,
    checked_at: "2026-11-19",
  });

  it("summarizes per row and shows each doctor's status side by side", async () => {
    const { BASELINE, ROWS_VS_BASELINE } = await import("./testdata");
    const a = {
      ...ROWS_VS_BASELINE[0],
      doctors: [
        doc("Ana Test", "listed", "✓ Listed in the plan's directory (checked Nov 19). Call to confirm."),
        doc(
          "Bo Test",
          "not_listed",
          "Not found in the plan's directory (checked Nov 19). May be out of network: call the plan.",
        ),
        doc("Cy Test", "unknown", "Couldn't check this plan's directory. Call the plan."),
      ],
    };
    const base = {
      ...BASELINE,
      doctors: [
        doc(
          "Ana Test",
          "original_medicare",
          "Original Medicare: any doctor who accepts Medicare. Not on the opt-out list (checked Nov 19).",
        ),
      ],
    };
    const { unmount } = render(<PlanTable rows={[a]} baseline={base} selected={[]} onSelect={() => {}} />);
    expect(screen.getByText("1 of 3 listed · 1 not found · 1 can't check")).toBeInTheDocument();
    expect(screen.getByText("Any doctor who accepts Medicare")).toBeInTheDocument();
    unmount();
    render(<SideBySide rows={[a]} fallback={[a]} baseline={base} />);
    expect(
      screen.getByText(/Listed in the plan's directory \(checked Nov 19\)\. Call to confirm\./),
    ).toBeInTheDocument();
    expect(screen.getByText(/Not on the opt-out list/)).toBeInTheDocument();
  });
});
