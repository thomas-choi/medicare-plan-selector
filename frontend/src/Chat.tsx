import { useEffect, useRef, useState } from "react";
import { ApiError, sendChat, type Canvas, type ChatMessage, type Profile } from "./api";
import { Markdown } from "./Markdown";

interface Props {
  history: ChatMessage[];
  enabled: boolean;
  maxChars: number;
  onCanvas: (c: Canvas) => void;
  onProfile: (p: Profile) => void;
  onToolCalls?: (ids: string[]) => void;
  onLimit: (msg: string) => void;
}

export function Chat({ history, enabled, maxChars, onCanvas, onProfile, onLimit }: Props) {
  const [msgs, setMsgs] = useState<ChatMessage[]>(history);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setMsgs(history);
  }, [history]);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [msgs]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError(null);
    setBusy(true);
    setMsgs((m) => [...m, { role: "user", content: text }, { role: "assistant", content: "" }]);
    try {
      await sendChat(text, {
        onDelta: (t) =>
          setMsgs((m) => {
            const copy = m.slice();
            const last = copy[copy.length - 1];
            copy[copy.length - 1] = { ...last, content: last.content + t };
            return copy;
          }),
        onCanvas,
        onProfile,
        onDone: (d) =>
          setMsgs((m) => {
            const copy = m.slice();
            copy[copy.length - 1] = { ...copy[copy.length - 1], citations: d.citations };
            return copy;
          }),
      });
    } catch (e) {
      setMsgs((m) => m.slice(0, -1));
      const msg = e instanceof ApiError ? e.message : "The assistant is unavailable right now.";
      setError(msg);
      if (e instanceof ApiError && (e.status === 429 || e.code === "no_llm")) onLimit(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="chat card" aria-label="Assistant">
      <h2>Ask the assistant</h2>
      {!enabled && (
        <p className="notice" role="status">
          The assistant is off right now. The form and comparison table still work.
        </p>
      )}
      <div className="messages" aria-live="polite">
        {msgs.length === 0 && enabled && (
          <p className="hint">
            Try: “Compare plans for me”, “Explain H0028_028_0”, or “Only show plans that cover all my drugs”.
          </p>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "assistant" ? <Markdown text={m.content || "…"} /> : <p>{m.content}</p>}
            {m.citations && m.citations.length > 0 && (
              <div className="chips" aria-label="Sources">
                {dedupeSources(m.citations).map((s) => (
                  <span className="chip" key={s} title="Data source">
                    {s}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <textarea
          aria-label="Message"
          rows={2}
          maxLength={maxChars}
          value={input}
          disabled={!enabled || busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button type="submit" className="primary" disabled={!enabled || busy || !input.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </form>
    </section>
  );
}

function dedupeSources(c: Record<string, unknown>[]): string[] {
  const s = new Set<string>();
  for (const r of c) {
    const src = typeof r.source === "string" ? r.source : null;
    const v = typeof r.vintage === "string" ? r.vintage : "";
    if (src) s.add(`${src}${v ? ` ${v}` : ""}`);
  }
  return [...s].slice(0, 8);
}
