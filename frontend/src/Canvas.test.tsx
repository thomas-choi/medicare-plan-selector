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
