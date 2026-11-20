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
