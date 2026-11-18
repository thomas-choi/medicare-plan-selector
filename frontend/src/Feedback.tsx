import { createContext, useContext, useState } from "react";
import { api, ApiError, type Mode } from "./api";

export const ModeContext = createContext<Mode>("nosave");

export function RatingWidget({ planKey, recommendationId }: { planKey: string; recommendationId?: string }) {
  const [sent, setSent] = useState<string | null>(null);
  const send = async (thumbs: 1 | -1) => {
    try {
      await api.feedback({
        kind: "recommendation_rating",
        thumbs,
        ...(recommendationId ? { recommendation_id: recommendationId } : { plan_key: planKey }),
      });
      setSent(thumbs === 1 ? "Thanks!" : "Thanks, noted.");
    } catch (e) {
      setSent(e instanceof ApiError ? e.message : "Couldn't send.");
    }
  };
  if (sent) return <p className="sent">{sent}</p>;
  return (
    <div className="rating" aria-label={`Rate this recommendation`}>
      <button aria-label="Helpful" onClick={() => send(1)}>
        👍
      </button>
      <button aria-label="Not helpful" onClick={() => send(-1)}>
        👎
      </button>
    </div>
  );
}

export function OutcomeCard({ planKeys }: { planKeys: { key: string; name: string }[] }) {
  const [choice, setChoice] = useState("undecided");
  const [enrolled, setEnrolled] = useState<"" | "yes" | "no" | "planned">("");
  const [confidence, setConfidence] = useState(0);
  const [done, setDone] = useState(false);
  if (done) return <p className="sent">Thanks for telling us.</p>;
  return (
    <form
      className="outcome card"
      aria-label="What did you decide?"
      onSubmit={async (e) => {
        e.preventDefault();
        await api.feedback({
          kind: "session_outcome",
          chosen_plan_key: choice,
          ...(enrolled ? { enrolled } : {}),
          ...(confidence ? { confidence } : {}),
        });
        setDone(true);
      }}
    >
      <h3>What did you decide?</h3>
      <select value={choice} onChange={(e) => setChoice(e.target.value)} aria-label="Plan you chose">
        <option value="undecided">Undecided</option>
        {planKeys.map((p) => (
          <option key={p.key} value={p.key}>
            {p.name}
          </option>
        ))}
        <option value="other">Another plan</option>
      </select>
      <select
        value={enrolled}
        onChange={(e) => setEnrolled(e.target.value as typeof enrolled)}
        aria-label="Enrolled?"
      >
        <option value="">Enrolled?</option>
        <option value="yes">Yes</option>
        <option value="planned">Planning to</option>
        <option value="no">No</option>
      </select>
      <select
        value={confidence}
        onChange={(e) => setConfidence(Number(e.target.value))}
        aria-label="Confidence"
      >
        <option value={0}>How sure are you?</option>
        {[1, 2, 3, 4, 5].map((n) => (
          <option key={n} value={n}>
            {n} / 5
          </option>
        ))}
      </select>
      <button type="submit">Send</button>
    </form>
  );
}

export const TEAM_NOTICE =
  "This message will be stored (redacted) for up to 365 days and is not linked to your session.";

export function FeedbackDialog({ onClose, lastToolCalls }: { onClose: () => void; lastToolCalls: string[] }) {
  const mode = useContext(ModeContext);
  const [kind, setKind] = useState<"general" | "bug">("general");
  const [text, setText] = useState("");
  const [details, setDetails] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  return (
    <div className="dialog-backdrop" role="presentation">
      <form
        role="dialog"
        aria-modal="true"
        aria-label={mode === "nosave" ? "Send a message to the team" : "Feedback"}
        className="dialog card"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api.feedback({
              kind,
              text,
              to_team: mode === "nosave",
              include_details: mode === "saved" && details,
              ...(kind === "bug"
                ? { context: { page: "main", view: "app", last_tool_call_ids: lastToolCalls.slice(-10) } }
                : {}),
            });
            setStatus("Thank you. Your message was sent.");
            setText("");
          } catch (err) {
            setStatus(err instanceof ApiError ? err.message : "Couldn't send.");
          }
        }}
      >
        <h2>{mode === "nosave" ? "Send a message to the team" : "Feedback"}</h2>
        <label>
          Type
          <select value={kind} onChange={(e) => setKind(e.target.value as "general" | "bug")}>
            <option value="general">General feedback</option>
            <option value="bug">Report a problem</option>
          </select>
        </label>
        <label>
          Message
          <textarea maxLength={2000} rows={5} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <p className="hint">
          Please don’t include personal details. We remove drug names, doctor names, phone numbers, ZIP codes
          and dates before storing.
        </p>
        {mode === "nosave" ? (
          <p className="notice" role="note">
            {TEAM_NOTICE}
          </p>
        ) : (
          <label className="check">
            <input type="checkbox" checked={details} onChange={(e) => setDetails(e.target.checked)} /> Include
            my details so the team can reproduce this (stored encrypted)
          </label>
        )}
        {status && <p role="status">{status}</p>}
        <div className="row">
          <button type="submit" className="primary" disabled={!text.trim()}>
            Send
          </button>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </form>
    </div>
  );
}
