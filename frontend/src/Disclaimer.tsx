// Text from DESIGN.md ("Shown on every page and in every export"). Do not reword without Thomas's approval.
export function Disclaimer() {
  return (
    <aside className="disclaimer" aria-label="Disclaimer">
      <p>
        This is an independent, free comparison tool. It is{" "}
        <strong>not a licensed insurance agent or broker</strong> and is{" "}
        <strong>not affiliated with or endorsed by CMS, Medicare or any plan</strong>.
      </p>
      <p>It earns no commissions.</p>
      <p>
        Costs are <strong>estimates</strong>. Confirm on{" "}
        <a href="https://www.medicare.gov/plan-compare/" rel="noreferrer" target="_blank">
          Medicare Plan Finder
        </a>
        , at 1-800-MEDICARE (1-800-633-4227), or with your state&apos;s SHIP counselor (
        <a href="https://www.shiphelp.org/local-medicare-help" rel="noreferrer" target="_blank">
          shiphelp.org/local-medicare-help
        </a>
        , 1-877-839-2675).
      </p>
    </aside>
  );
}
