export function money(cents: number | null | undefined, opts: { whole?: boolean } = {}): string {
  if (cents === null || cents === undefined) return "no cap";
  const v = cents / 100;
  return v.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: opts.whole ? 0 : 2,
    maximumFractionDigits: opts.whole ? 0 : 2,
  });
}

export function range(lo: number, hi: number): string {
  return lo === hi
    ? money(lo, { whole: true })
    : `${money(lo, { whole: true })}–${money(hi, { whole: true })}`;
}

export function stars(s: number | null): string {
  return s === null ? "not rated" : `${s.toFixed(1)}★`;
}

/** Yearly difference to the standard Original Medicare + Part D option: "$1,234 less" / "$567 more". */
export function delta(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "—";
  if (cents === 0) return "same";
  const v = money(Math.abs(cents), { whole: true });
  return cents < 0 ? `${v} less` : `${v} more`;
}

/** Worst case per year; the baseline without Medigap has no yearly limit. */
export function worstCase(r: { worst_case_cents: number | null; is_baseline?: boolean }): string {
  if (r.worst_case_cents === null && r.is_baseline) return "No limit";
  return money(r.worst_case_cents, { whole: true });
}

/** One-line doctor badge for a table cell (addendum A3.3): "1 of 2 listed · 1 not found", "Any doctor who accepts
 * Medicare". Doctors typed by name only (no NPI) aren't counted. */
export function doctorSummary(
  doctors: { status: string }[] | undefined,
  opts: { original?: boolean } = {},
): string {
  const checked = (doctors ?? []).filter((d) => d.status !== "no_npi");
  if (!checked.length) return opts.original ? "Any doctor who accepts Medicare" : "—";
  const n = (s: string) => checked.filter((d) => d.status === s).length;
  if (n("original_medicare") + n("opted_out") > 0) {
    return n("opted_out") ? `${n("opted_out")} opted out of Medicare` : "Any doctor who accepts Medicare";
  }
  const parts = [`${n("listed")} of ${checked.length} listed`];
  if (n("not_listed")) parts.push(`${n("not_listed")} not found`);
  const cant = n("unknown") + n("unavailable");
  if (cant) parts.push(`${cant} can't check`);
  return parts.join(" · ");
}
