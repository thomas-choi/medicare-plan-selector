import { useEffect, useRef } from "react";
import type { GlossaryTerm, PlanRow } from "./api";
import { money } from "./format";

const mid = (lo: number, hi: number) => Math.floor((lo + hi) / 2);

/** "Est. yearly cost" vs "Worst case" for the user's own top-ranked plan, line by line. */
function Example({ r }: { r: PlanRow }) {
  if (r.worst_case_cents === null) return null;
  // Derived from the totals so each column adds up exactly (no separate rounding per line).
  const drugMid = mid(r.drug_low_cents, r.drug_high_cents);
  const medicalMid = r.total_est_cents - r.premium_annual_cents - r.part_b_annual_cents - drugMid;
  const medicalWorst =
    r.worst_case_cents - r.premium_annual_cents - r.part_b_annual_cents - r.drug_high_cents;
  return (
    <section aria-label="Example from your comparison">
      <h3>Example: {r.plan_name}</h3>
      <table className="info-example">
        <thead>
          <tr>
            <th></th>
            <th>Est. yearly cost (typical year)</th>
            <th>Worst case (bad year)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Plan premium</td>
            <td>{money(r.premium_annual_cents)}</td>
            <td>{money(r.premium_annual_cents)}</td>
          </tr>
          <tr>
            <td>Part B premium</td>
            <td>{money(r.part_b_annual_cents)}</td>
            <td>{money(r.part_b_annual_cents)}</td>
          </tr>
          <tr>
            <td>Your drugs</td>
            <td>{money(drugMid)} (middle of the range)</td>
            <td>{money(r.drug_high_cents)} (high end)</td>
          </tr>
          <tr>
            <td>Medical care</td>
            <td>{money(medicalMid)} (for your usage level)</td>
            <td>{money(medicalWorst)} (the MOOP)</td>
          </tr>
          <tr className="total">
            <td>Total</td>
            <td>{money(r.total_est_cents)}</td>
            <td>{money(r.worst_case_cents)}</td>
          </tr>
        </tbody>
      </table>
      {r.part_d_deductible_cents !== null && (
        <p className="sub">
          The {money(r.part_d_deductible_cents)} Part D deductible is already inside the drug cost.
        </p>
      )}
    </section>
  );
}

export function ImportantInfoDialog({
  glossary,
  example,
  onClose,
}: {
  glossary: GlossaryTerm[];
  example?: PlanRow;
  onClose: () => void;
}) {
  const close = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    close.current?.focus(); // once on open, not on every parent re-render
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Important information"
        className="dialog card info-dialog"
      >
        <h2>Important information</h2>
        <p>What the columns in the comparison mean. All costs are estimates, not quotes.</p>
        <dl className="glossary">
          {glossary.map((t) => (
            <div key={t.id}>
              <dt>{t.title}</dt>
              <dd>{t.text}</dd>
            </div>
          ))}
        </dl>
        {example && <Example r={example} />}
        <p>
          Confirm your finalists in Medicare Plan Finder, at 1-800-MEDICARE (1-800-633-4227), or with your
          SHIP (1-877-839-2675).
        </p>
        <button ref={close} onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
