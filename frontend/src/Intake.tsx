import { useState } from "react";
import { api, ApiError, type County, type Drug, type Pharmacy, type Profile } from "./api";

interface Props {
  profile: Profile;
  maxDrugs: number;
  maxProviders: number;
  busy: boolean;
  onSubmit: (p: Profile) => void;
}

const STATES =
  "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR VI GU AS MP".split(
    " ",
  );

export function Intake({ profile, maxDrugs, maxProviders, busy, onSubmit }: Props) {
  const [p, setP] = useState<Profile>(profile);
  const [zip, setZip] = useState(profile.zip ?? "");
  const [counties, setCounties] = useState<County[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [pickState, setPickState] = useState("");
  const [drugQ, setDrugQ] = useState("");
  const [cands, setCands] = useState<{ rxcui: string; name: string }[]>([]);
  // Drug search status, always visible so a search never looks like "no response" (Thomas's 2026-11-19 report).
  const [drugStatus, setDrugStatus] = useState<
    | { kind: "idle" }
    | { kind: "searching"; q: string }
    | { kind: "found"; q: string; n: number; matchedAs: string | null }
    | { kind: "empty"; q: string }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const [manualRx, setManualRx] = useState("");
  const [rxErr, setRxErr] = useState<string | null>(null);
  const [doctor, setDoctor] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const set = (u: Partial<Profile>) => setP((old) => ({ ...old, ...u }));
  const choose = (c: County) =>
    set({ zip, county_ssa: c.ssa_code, county_name: c.county, state: c.state ?? undefined });

  async function lookupZip() {
    setErr(null);
    if (!/^\d{5}$/.test(zip)) return setErr("Enter a 5-digit ZIP code.");
    try {
      const r = await api.location(zip);
      setCounties(r.counties);
      setNote(r.note);
      if (r.counties.length === 1) choose(r.counties[0]);
      else set({ zip, county_ssa: null, county_name: null });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "ZIP lookup failed.");
    }
  }

  async function loadState(s: string) {
    setPickState(s);
    if (!s) return;
    const r = await api.counties(s);
    setCounties(r.counties);
  }

  async function searchDrug() {
    setErr(null);
    const q = drugQ.trim();
    if (q.length < 2) {
      setCands([]);
      return setDrugStatus({ kind: "error", message: "Type at least 2 letters of the drug name." });
    }
    setDrugStatus({ kind: "searching", q });
    try {
      const r = await api.drugs(q);
      setCands(r.candidates);
      setDrugStatus(
        r.candidates.length
          ? { kind: "found", q, n: r.candidates.length, matchedAs: r.matched_as ?? null }
          : { kind: "empty", q },
      );
    } catch (e) {
      setCands([]);
      setDrugStatus({
        kind: "error",
        message:
          e instanceof ApiError
            ? `${e.message} You can enter the drug's RxCUI instead.`
            : "Drug search failed. You can enter the drug's RxCUI instead.",
      });
    }
  }

  function addDrug(d: Drug) {
    if (p.drugs.length >= maxDrugs) return setErr(`Up to ${maxDrugs} drugs.`);
    set({ drugs: [...p.drugs, { days_supply: 30, pharmacy: p.pharmacy_preference, ...d }] });
    setCands([]);
    setDrugQ("");
    setManualRx("");
    setDrugStatus({ kind: "idle" });
  }

  // RxCUI-only entry is the documented offline path (drug search needs RxNav). The typed drug name, if any, is the
  // label; otherwise the RxCUI itself. No name lookup: the plan data has RxCUIs but no drug names.
  function addByRxcui() {
    setRxErr(null);
    const rx = manualRx.trim();
    if (!/^\d+$/.test(rx)) return setRxErr("An RxCUI is a number, e.g. 197361.");
    if (rx.length > 10) return setRxErr("An RxCUI has 1 to 10 digits.");
    if (p.drugs.some((d) => d.rxcui === rx)) return setRxErr(`RxCUI ${rx} is already on your list.`);
    const name = drugQ.trim().length >= 2 ? drugQ.trim().slice(0, 120) : `RxCUI ${rx}`;
    addDrug({ name, rxcui: rx });
  }

  const updateDrug = (i: number, u: Partial<Drug>) =>
    set({ drugs: p.drugs.map((d, j) => (j === i ? { ...d, ...u } : d)) });

  return (
    <form
      className="intake card"
      aria-label="Your situation"
      onSubmit={(e) => {
        e.preventDefault();
        if (!p.county_ssa) return setErr("Pick your county first.");
        onSubmit(p);
      }}
    >
      <h2>Your situation</h2>
      <div className="row">
        <label>
          ZIP code
          <input
            inputMode="numeric"
            maxLength={5}
            value={zip}
            onChange={(e) => setZip(e.target.value.replace(/\D/g, ""))}
            aria-label="ZIP code"
          />
        </label>
        <button type="button" onClick={lookupZip}>
          Find county
        </button>
      </div>
      {note && (
        <div className="note">
          <p>{note}</p>
          <label>
            State
            <select value={pickState} onChange={(e) => loadState(e.target.value)} aria-label="State">
              <option value="">Choose…</option>
              {STATES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
      )}
      {counties.length > 0 && (
        <label>
          County
          <select
            aria-label="County"
            value={p.county_ssa ?? ""}
            onChange={(e) => {
              const c = counties.find((x) => x.ssa_code === e.target.value);
              if (c) choose(c);
            }}
          >
            <option value="">Choose…</option>
            {counties.map((c) => (
              <option key={c.ssa_code} value={c.ssa_code}>
                {c.county}, {c.state}
                {c.res_ratio !== null && c.res_ratio < 1
                  ? ` (${Math.round(c.res_ratio * 100)}% of this ZIP)`
                  : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {p.county_name && <p className="ok">County: {p.county_name}</p>}

      <h3>Drugs</h3>
      <div className="row">
        <input
          placeholder="Drug name, e.g. metformin"
          value={drugQ}
          onChange={(e) => setDrugQ(e.target.value)}
          onKeyDown={(e) => {
            // Enter searches; it must not submit the whole form ("Compare plans").
            if (e.key === "Enter") {
              e.preventDefault();
              void searchDrug();
            }
          }}
          aria-label="Drug name"
        />
        <button type="button" onClick={searchDrug} disabled={drugStatus.kind === "searching"}>
          {drugStatus.kind === "searching" ? "Searching…" : "Search"}
        </button>
      </div>
      <p className="hint" role="status" aria-live="polite" aria-label="Drug search status">
        {drugStatus.kind === "searching" && `Searching for “${drugStatus.q}”…`}
        {drugStatus.kind === "found" &&
          (drugStatus.matchedAs
            ? `No exact match for “${drugStatus.q}”. Showing ${drugStatus.n} result(s) for “${drugStatus.matchedAs}”: pick your strength and form.`
            : `${drugStatus.n} match(es) for “${drugStatus.q}”. Pick yours below.`)}
        {drugStatus.kind === "empty" &&
          `No drugs found for “${drugStatus.q}”. Try just the drug name (e.g. “tamsulosin”), check the spelling, or add it by RxCUI.`}
      </p>
      {drugStatus.kind === "error" && (
        <p role="alert" className="error">
          {drugStatus.message}
        </p>
      )}
      {cands.length > 0 && (
        <ul className="candidates" aria-label="Drug matches">
          {cands.map((c) => (
            <li key={c.rxcui}>
              <button type="button" onClick={() => addDrug({ name: c.name, rxcui: c.rxcui })}>
                Add {c.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="row small">
        <input
          placeholder="or RxCUI (numbers)"
          value={manualRx}
          inputMode="numeric"
          onChange={(e) => setManualRx(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addByRxcui();
            }
          }}
          aria-label="RxCUI"
        />
        <button type="button" disabled={!manualRx.trim()} onClick={addByRxcui}>
          Add by RxCUI
        </button>
      </div>
      {rxErr && (
        <p role="alert" className="error">
          {rxErr}
        </p>
      )}
      <ul className="drugs">
        {p.drugs.map((d, i) => (
          <li key={`${d.rxcui}-${i}`}>
            <span>{d.name}</span>
            <select
              aria-label={`Days supply for ${d.name}`}
              value={d.days_supply ?? 30}
              onChange={(e) => updateDrug(i, { days_supply: Number(e.target.value) as 30 | 60 | 90 })}
            >
              <option value={30}>30-day</option>
              <option value={60}>60-day</option>
              <option value={90}>90-day</option>
            </select>
            <input
              aria-label={`Price per fill for ${d.name} (optional)`}
              placeholder="$ per fill (optional)"
              inputMode="decimal"
              value={d.price_per_fill_cents ? (d.price_per_fill_cents / 100).toString() : ""}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                updateDrug(i, { price_per_fill_cents: Number.isFinite(v) ? Math.round(v * 100) : null });
              }}
            />
            <button type="button" onClick={() => set({ drugs: p.drugs.filter((_, j) => j !== i) })}>
              Remove
            </button>
          </li>
        ))}
      </ul>

      <h3>Doctors (optional)</h3>
      <div className="row">
        <input
          placeholder="Doctor's name"
          value={doctor}
          onChange={(e) => setDoctor(e.target.value)}
          aria-label="Doctor name"
        />
        <button
          type="button"
          disabled={!doctor.trim() || p.providers.length >= maxProviders}
          onClick={() => {
            set({ providers: [...p.providers, { name: doctor.trim() }] });
            setDoctor("");
          }}
        >
          Add
        </button>
      </div>
      {p.providers.length > 0 && (
        <ul className="drugs">
          {p.providers.map((d, i) => (
            <li key={i}>
              <span>{d.name}</span>
              <button type="button" onClick={() => set({ providers: p.providers.filter((_, j) => j !== i) })}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="hint">Public CMS files don’t list networks. Call each plan to confirm your doctors.</p>

      <h3>Preferences</h3>
      <div className="grid2">
        <label>
          Coverage path
          <select value={p.path} onChange={(e) => set({ path: e.target.value as Profile["path"] })}>
            <option value="both">Show both</option>
            <option value="ma">Medicare Advantage</option>
            <option value="original">Original Medicare + Part D</option>
          </select>
        </label>
        <label>
          Expected health care use
          <select
            value={p.utilization}
            onChange={(e) => set({ utilization: e.target.value as Profile["utilization"] })}
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
        <label>
          Pharmacy
          <select
            value={p.pharmacy_preference}
            onChange={(e) => set({ pharmacy_preference: e.target.value as Pharmacy })}
          >
            <option value="retail">Retail</option>
            <option value="pref_retail">Preferred retail</option>
            <option value="mail">Mail order</option>
            <option value="pref_mail">Preferred mail order</option>
          </select>
        </label>
        <label>
          Minimum star rating
          <select
            value={p.must_haves.min_stars ?? ""}
            onChange={(e) =>
              set({
                must_haves: { ...p.must_haves, min_stars: e.target.value ? Number(e.target.value) : null },
              })
            }
          >
            <option value="">Any</option>
            <option value="3">3+</option>
            <option value="3.5">3.5+</option>
            <option value="4">4+</option>
            <option value="4.5">4.5+</option>
          </select>
        </label>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={!!p.must_haves.all_drugs_covered}
          onChange={(e) => set({ must_haves: { ...p.must_haves, all_drugs_covered: e.target.checked } })}
        />{" "}
        Only plans that cover all my drugs
      </label>
      {err && (
        <p role="alert" className="error">
          {err}
        </p>
      )}
      <button className="primary" type="submit" disabled={busy}>
        {busy ? "Comparing…" : "Compare plans"}
      </button>
    </form>
  );
}
