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
