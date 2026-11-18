import { useState } from "react";
import type { AppConfig, Mode } from "./api";

interface Props {
  config: AppConfig;
  onStart: (mode: Mode, feedbackPhi: boolean) => void;
  busy?: boolean;
  error?: string | null;
}

// DESIGN §8.1/§8.5: shown before anything is saved; says what is stored, for how long, and who receives it.
export function Consent({ config, onStart, busy, error }: Props) {
  const savedAvailable = config.modes.includes("saved");
  const [mode, setMode] = useState<Mode>(
    config.default_mode === "saved" && savedAvailable ? "saved" : "nosave",
  );
  const [accepted, setAccepted] = useState(false);
  const [phi, setPhi] = useState(false);
  const provider = config.llm_provider_label;
  return (
    <section className="consent card" aria-labelledby="consent-title">
      <h2 id="consent-title">Before we start</h2>
      <p>
        This tool compares {config.plan_year} Medicare Advantage and Part D plans using public CMS data. It
        gives estimates, not quotes, and it never enrolls you in anything.
      </p>
      <fieldset>
        <legend>How should we handle your information?</legend>
        <label className={`mode-option ${mode === "nosave" ? "selected" : ""}`}>
          <input
            type="radio"
            name="mode"
            value="nosave"
            checked={mode === "nosave"}
            onChange={() => setMode("nosave")}
          />
          <span>
            <strong>No-save (recommended)</strong>: nothing is kept on our servers after you finish or after{" "}
            {config.ephemeral_idle_minutes} minutes idle (at most {config.ephemeral_max_hours} hours). You can
            download your comparison first.
          </span>
        </label>
        <label
          className={`mode-option ${mode === "saved" ? "selected" : ""} ${savedAvailable ? "" : "disabled"}`}
        >
          <input
            type="radio"
            name="mode"
            value="saved"
            disabled={!savedAvailable}
            checked={mode === "saved"}
            onChange={() => setMode("saved")}
          />
          <span>
            <strong>Save for {config.retention_days} days</strong>: your ZIP, drugs, doctors and chat are
            stored encrypted so you can come back. Deleted after {config.retention_days} days without a visit,
            or any time with “Delete my data”.
            {!savedAvailable && " (Not available right now.)"}
          </span>
        </label>
      </fieldset>
      <details>
        <summary>Who receives what</summary>
        <ul>
          <li>
            {provider ? (
              <>
                The AI assistant is run by <strong>{provider}</strong>. Your chat messages are sent to it; its
                own retention policy applies to what it receives.
              </>
            ) : (
              <>The AI assistant is off; you can still compare plans with the form.</>
            )}
          </li>
          <li>
            Drug names go to the National Library of Medicine (RxNav), doctor names to the CMS NPI Registry,
            and ZIP codes to HUD, without anything that identifies you.
          </li>
          <li>
            We use no ads, no analytics and no tracking cookies. We sell nothing and earn no commissions.
          </li>
          <li>Feedback is optional; free text is redacted before it is stored.</li>
        </ul>
      </details>
      {mode === "saved" && (
        <label className="check">
          <input type="checkbox" checked={phi} onChange={(e) => setPhi(e.target.checked)} /> I may include
          details in feedback so the team can reproduce problems (stored encrypted).
        </label>
      )}
      <label className="check">
        <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} /> I
        understand this is an estimate tool, not insurance advice.
      </label>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <button className="primary" disabled={!accepted || busy} onClick={() => onStart(mode, phi)}>
        Start
      </button>
    </section>
  );
}
