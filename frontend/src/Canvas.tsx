import { useMemo, useState } from "react";
import type { Canvas as CanvasT, PlanRow } from "./api";
import { delta, money, range, stars, worstCase } from "./format";
import { RatingWidget } from "./Feedback";

type Tab = "table" | "chart" | "side_by_side" | "checklist";
type SortKey = "rank" | "total_est_cents" | "monthly_premium_cents" | "worst_case_cents" | "star_overall";

interface Props {
  canvas: CanvasT;
  checklist: string[];
  estimateDisclaimer: string;
  tab: Tab;
  onTab: (t: Tab) => void;
  selected: string[];
  onSelect: (keys: string[]) => void;
}

export function Canvas({ canvas, checklist, estimateDisclaimer, tab, onTab, selected, onSelect }: Props) {
  const rows = useMemo(() => canvas.rows ?? [], [canvas.rows]);
  const tabs: [Tab, string][] = [
    ["table", "Table"],
    ["chart", "Cost chart"],
    ["side_by_side", "Side-by-side"],
    ["checklist", "Checklist"],
  ];
  if (!rows.length && tab !== "checklist") {
    return (
      <section className="canvas card" aria-label="Comparison">
        <p className="empty">
          Fill in your ZIP and drugs, then choose “Compare plans”, or ask the assistant.
        </p>
      </section>
    );
  }
  const top = rows.filter((r) => r.rank !== null).slice(0, 3);
  return (
    <section className="canvas card" aria-label="Comparison">
      {top.length > 0 && (
        <div className="top3">
          {top.map((r) => (
            <article className="plan-card" key={r.plan_key} aria-label={`Rank ${r.rank}: ${r.plan_name}`}>
              <div className="rank">#{r.rank}</div>
              <h3>{r.plan_name}</h3>
              <p className="org">
                {r.organization} · {r.plan_type ?? r.category} · {r.plan_key} · {stars(r.star_overall)}
              </p>
              <p className="total">
                Estimated yearly cost <strong>{range(r.total_low_cents, r.total_high_cents)}</strong>
              </p>
              <p>
                Premium {money(r.monthly_premium_cents)}/mo · Drugs{" "}
                {range(r.drug_low_cents, r.drug_high_cents)}
                /yr · Worst case {money(r.worst_case_cents, { whole: true })}
              </p>
              <p>
                Covers {r.drugs_covered} of {r.drugs_total} drugs
              </p>
              <RatingWidget planKey={r.plan_key} recommendationId={canvas.recommendation_ids?.[r.plan_key]} />
            </article>
          ))}
        </div>
      )}
      <div role="tablist" className="tabs">
        {tabs.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => onTab(t)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "table" && (
        <PlanTable rows={rows} baseline={canvas.baseline} selected={selected} onSelect={onSelect} />
      )}
      {tab === "chart" && <CostChart rows={rows.filter((r) => r.rank !== null).slice(0, 10)} />}
      {tab === "side_by_side" && (
        <SideBySide
          rows={rows.filter((r) => selected.includes(r.plan_key))}
          fallback={top}
          baseline={canvas.baseline}
        />
      )}
      {tab === "checklist" && (
        <ol className="checklist">
          {checklist.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ol>
      )}
      <footer className="estimate-note">
        <p>{estimateDisclaimer}</p>
        {canvas.notes && canvas.notes.length > 0 && (
          <details>
            <summary>How we estimate</summary>
            <ul>
              {canvas.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </details>
        )}
      </footer>
    </section>
  );
}

/** The pinned "Original Medicare + Part D (standard)" row's subtitle: what it is made of. */
export function baselineParts(b: PlanRow): string {
  const parts = ["Part A", "Part B", b.pdp_plan_name ? `drug plan ${b.pdp_plan_name}` : "no drug plan found"];
  if (b.medigap?.plan) parts.push(b.components?.find((c) => c.kind === "medigap")?.label ?? "Medigap");
  return parts.join(" + ");
}

export function PlanTable({
  rows,
  baseline,
  selected,
  onSelect,
}: {
  rows: PlanRow[];
  baseline?: PlanRow;
  selected: string[];
  onSelect: (k: string[]) => void;
}) {
  const [sort, setSort] = useState<SortKey>("rank");
  const [asc, setAsc] = useState(true);
  const sorted = useMemo(() => {
    const val = (r: PlanRow): number => {
      const v = r[sort];
      if (v === null || v === undefined) return sort === "star_overall" ? -1 : Number.MAX_SAFE_INTEGER;
      return v as number;
    };
    const ranked = rows.filter((r) => r.rank !== null).sort((a, b) => (asc ? 1 : -1) * (val(a) - val(b)));
    return [...ranked, ...rows.filter((r) => r.rank === null)];
  }, [rows, sort, asc]);
  const th = (k: SortKey, label: string) => (
    <th aria-sort={sort === k ? (asc ? "ascending" : "descending") : "none"}>
      <button
        onClick={() => {
          if (sort === k) setAsc(!asc);
          else {
            setSort(k);
            setAsc(k !== "star_overall");
          }
        }}
      >
        {label}
      </button>
    </th>
  );
  const toggle = (k: string) =>
    onSelect(selected.includes(k) ? selected.filter((x) => x !== k) : [...selected, k].slice(-5));
  return (
    <div className="table-wrap">
      <table className="plans">
        <thead>
          <tr>
            <th>Compare</th>
            {th("rank", "Rank")}
            <th>Plan</th>
            {th("total_est_cents", "Est. yearly cost")}
            {th("monthly_premium_cents", "Premium/mo")}
            {th("worst_case_cents", "Worst case")}
            {th("star_overall", "Stars")}
            <th>Drugs covered</th>
            <th>vs. standard</th>
          </tr>
        </thead>
        <tbody>
          {baseline && (
            // Pinned first row: never sorted, never ranked, always shown (addendum A5.4).
            <tr className="baseline" aria-label={`Standard: ${baseline.plan_name}`}>
              <td>
                <span className="sub">Always compared</span>
              </td>
              <td>
                <span className="badge">Standard</span>
              </td>
              <td>
                <div>{baseline.plan_name}</div>
                <div className="sub">{baselineParts(baseline)}</div>
              </td>
              <td>{range(baseline.total_low_cents, baseline.total_high_cents)}</td>
              <td>
                {money(baseline.monthly_premium_cents)}
                <div className="sub">+ Part B</div>
              </td>
              <td>{worstCase(baseline)}</td>
              <td>{stars(null)}</td>
              <td>
                {baseline.drugs_covered}/{baseline.drugs_total}
              </td>
              <td>—</td>
            </tr>
          )}
          {sorted.map((r) => (
            <tr key={r.plan_key} className={r.rank === null ? "dropped" : ""}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`Select ${r.plan_name} for side-by-side`}
                  checked={selected.includes(r.plan_key)}
                  onChange={() => toggle(r.plan_key)}
                />
              </td>
              <td>{r.rank ?? "—"}</td>
              <td>
                <div>{r.plan_name}</div>
                <div className="sub">
                  {r.organization} · {r.plan_key}
                </div>
                {r.dropped_reason && <div className="reason">Not ranked: {r.dropped_reason}</div>}
              </td>
              <td>{range(r.total_low_cents, r.total_high_cents)}</td>
              <td>{money(r.monthly_premium_cents)}</td>
              <td>{money(r.worst_case_cents, { whole: true })}</td>
              <td>{stars(r.star_overall)}</td>
              <td>
                {r.drugs_covered}/{r.drugs_total}
              </td>
              <td>{baseline ? delta(r.delta_vs_baseline_cents) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CostChart({ rows }: { rows: PlanRow[] }) {
  if (!rows.length) return <p>No ranked plans to chart.</p>;
  const max = Math.max(...rows.map((r) => Math.max(r.total_high_cents, r.worst_case_cents ?? 0)), 1);
  const W = 640;
  const label = 230;
  const barH = 22;
  const gap = 12;
  const scale = (c: number) => (c / max) * (W - label - 20);
  const H = rows.length * (barH + gap) + 30;
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Estimated yearly cost by plan">
        {rows.map((r, i) => {
          const y = i * (barH + gap) + 4;
          const parts = [
            { v: r.premium_annual_cents + r.part_b_annual_cents, cls: "premium" },
            { v: r.drug_low_cents, cls: "drug" },
            { v: r.medical_low_cents, cls: "medical" },
          ];
          let x = label;
          return (
            <g key={r.plan_key}>
              <text x={0} y={y + barH * 0.72} className="bar-label">
                {r.plan_name.length > 28 ? `${r.plan_name.slice(0, 27)}…` : r.plan_name}
              </text>
              {parts.map((p) => {
                const w = scale(p.v);
                const el = (
                  <rect key={p.cls} x={x} y={y} width={Math.max(w, 0)} height={barH} className={p.cls} />
                );
                x += w;
                return el;
              })}
              {r.worst_case_cents !== null && (
                <line
                  x1={label + scale(r.worst_case_cents)}
                  x2={label + scale(r.worst_case_cents)}
                  y1={y - 3}
                  y2={y + barH + 3}
                  className="worst"
                >
                  <title>Worst case {money(r.worst_case_cents, { whole: true })}</title>
                </line>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption>
        <span className="key premium" /> Premiums (incl. Part B) <span className="key drug" /> Drugs{" "}
        <span className="key medical" /> Medical (low estimate) <span className="key worst" /> Worst case
        (yearly out-of-pocket cap + premiums)
      </figcaption>
    </figure>
  );
}

export function SideBySide({
  rows,
  fallback,
  baseline,
}: {
  rows: PlanRow[];
  fallback: PlanRow[];
  baseline?: PlanRow;
}) {
  const plans = (rows.length >= 2 ? rows : fallback).slice(0, 5);
  if (plans.length < (baseline ? 1 : 2))
    return <p>Select 2–5 plans in the table to compare them side by side.</p>;
  // The standard Original Medicare + Part D option is always the first column (addendum A5.4).
  const show = baseline ? [baseline, ...plans] : plans;
  const lines: [string, (r: PlanRow) => string][] = [
    ["Plan ID", (r) => (r.is_baseline ? `Drug plan ${r.pdp_plan_key ?? "none"}` : r.plan_key)],
    ["Type", (r) => `${r.plan_type ?? r.category}`],
    ["Stars", (r) => stars(r.star_overall)],
    ["Premium / month", (r) => money(r.monthly_premium_cents)],
    ["Part B premium / month", (r) => money(r.part_b_annual_cents / 12)],
    [
      "Deductibles",
      (r) =>
        r.is_baseline
          ? `Part B ${money(r.part_b_deductible_cents ?? 0, { whole: true })} + drugs ${money(r.part_d_deductible_cents ?? 0)}`
          : `Drugs ${money(r.part_d_deductible_cents ?? 0)}`,
    ],
    [
      "Yearly out-of-pocket cap (in network)",
      (r) => (r.is_baseline && r.moop_cents === null ? "No limit" : money(r.moop_cents, { whole: true })),
    ],
    ["Drug costs / year", (r) => range(r.drug_low_cents, r.drug_high_cents)],
    ["Medical costs / year", (r) => range(r.medical_low_cents, r.medical_high_cents)],
    ["Estimated total / year", (r) => range(r.total_low_cents, r.total_high_cents)],
    ["vs. standard / year", (r) => (r.is_baseline ? "—" : delta(r.delta_vs_baseline_cents))],
    ["Worst case / year", (r) => worstCase(r)],
    ["Drugs covered", (r) => `${r.drugs_covered} of ${r.drugs_total}`],
  ];
  return (
    <div className="table-wrap">
      <table className="sbs">
        <thead>
          <tr>
            <th />
            {show.map((r) => (
              <th key={r.plan_key} className={r.is_baseline ? "baseline" : undefined}>
                {r.is_baseline && <span className="badge">Standard</span>} {r.plan_name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map(([label, f]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              {show.map((r) => (
                <td key={r.plan_key}>{f(r)}</td>
              ))}
            </tr>
          ))}
          <tr>
            <th scope="row">Your drugs</th>
            {show.map((r) => (
              <td key={r.plan_key}>
                <ul>
                  {r.drugs.map((d) => (
                    <li key={d.name}>
                      {d.name}: {d.covered ? `tier ${d.tier ?? "?"}` : "not covered"}
                      {d.restrictions.length > 0 && ` (${d.restrictions.join(", ")})`}
                    </li>
                  ))}
                </ul>
              </td>
            ))}
          </tr>
          {baseline && (
            <tr>
              <th scope="row">Notes</th>
              {show.map((r) => (
                <td key={r.plan_key}>
                  {r.is_baseline && (
                    <ul>
                      {r.medigap?.rule_note && <li>{r.medigap.rule_note}</li>}
                      {r.notes.map((n) => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  )}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
