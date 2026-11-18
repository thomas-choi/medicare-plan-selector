import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  beaconEnd,
  emptyProfile,
  type AppConfig,
  type Canvas as CanvasT,
  type ChatMessage,
  type Mode,
  type Profile,
} from "./api";
import { Canvas } from "./Canvas";
import { Chat } from "./Chat";
import { Consent } from "./Consent";
import { Disclaimer } from "./Disclaimer";
import { comparisonMarkdown, download } from "./exportMd";
import { FeedbackDialog, ModeContext, OutcomeCard } from "./Feedback";
import { Header } from "./Header";
import { Intake } from "./Intake";

type Tab = "table" | "chart" | "side_by_side" | "checklist";

// All state lives in memory only (DESIGN §8.5 Browser): no localStorage, sessionStorage or IndexedDB.
export function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [mode, setMode] = useState<Mode | null>(null);
  const [profile, setProfile] = useState<Profile>(emptyProfile());
  const [profileVersion, setProfileVersion] = useState(0);
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [canvas, setCanvas] = useState<CanvasT>({});
  const [tab, setTab] = useState<Tab>("table");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const [cfg, s] = await Promise.all([api.config(), api.session()]);
      setConfig(cfg);
      if (s.session) {
        setMode(s.session.mode);
        setProfile(s.profile ?? emptyProfile());
        setProfileVersion((v) => v + 1);
        setHistory(s.chat ?? []);
        setCanvas(s.canvas ?? {});
        if (s.renewed) setNotice("Your earlier No-save session ended, so nothing from it was kept.");
      }
    } catch {
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (mode !== "nosave") return;
    const h = () => beaconEnd();
    window.addEventListener("pagehide", h);
    return () => window.removeEventListener("pagehide", h);
  }, [mode]);

  const applyCanvas = (c: CanvasT) => {
    setCanvas(c);
    if (c.tab) setTab(c.tab);
    if (c.selected) setSelected(c.selected);
  };

  async function start(m: Mode, phi: boolean) {
    if (!config) return;
    setBusy(true);
    setError(null);
    try {
      await api.start(m, config.consent_version, phi);
      setMode(m);
      setProfile(emptyProfile());
      setProfileVersion((v) => v + 1);
      setHistory([]);
      setCanvas({});
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start a session.");
    } finally {
      setBusy(false);
    }
  }

  async function compare(p: Profile) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.compare(p);
      setProfile(p);
      applyCanvas({ ...r.canvas, tab: "table" });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Comparison failed.");
    } finally {
      setBusy(false);
    }
  }

  async function erase() {
    const msg =
      mode === "nosave"
        ? "End this session and erase everything now? Download your comparison first if you want to keep it."
        : "Delete your saved profile, chat and feedback details now? This can't be undone.";
    if (!window.confirm(msg)) return;
    try {
      await api.erase();
    } finally {
      setMode(null);
      setProfile(emptyProfile());
      setHistory([]);
      setCanvas({});
      setSelected([]);
      setNotice(mode === "nosave" ? "Session ended. Everything was erased." : "Your data was deleted.");
      void load();
    }
  }

  const canDownload = !!canvas.rows?.length;
  const doDownload = () => {
    if (!config) return;
    download(
      `medicare-comparison-${config.plan_year}.md`,
      comparisonMarkdown(canvas, profile, config.checklist, config.plan_year),
    );
  };

  const llmOn = !!config?.llm_enabled;
  const ranked = (canvas.rows ?? []).filter((r) => r.rank !== null).slice(0, 5);

  return (
    <ModeContext.Provider value={mode ?? "nosave"}>
      <div className="app">
        <Header
          mode={mode}
          onErase={erase}
          onFeedback={() => setFeedbackOpen(true)}
          onDownload={doDownload}
          canDownload={canDownload}
        />
        {notice && (
          <p className="notice" role="status">
            {notice}{" "}
            <button className="link" onClick={() => setNotice(null)}>
              Dismiss
            </button>
          </p>
        )}
        {mode === "nosave" && (
          <p className="mode-line">
            No-save: nothing is kept on our servers after you finish or after{" "}
            {config?.ephemeral_idle_minutes ?? 30} minutes idle. You can download your comparison first.
          </p>
        )}
        <main>
          {loadFailed && (
            <p role="alert" className="error">
              The service is unavailable right now. Please try again later.
            </p>
          )}
          {config && !mode && <Consent config={config} onStart={start} busy={busy} error={error} />}
          {config && mode && (
            <div className="workspace">
              <div className="left">
                <Intake
                  key={profileVersion}
                  profile={profile}
                  maxDrugs={config.limits.drugs}
                  maxProviders={config.limits.providers}
                  busy={busy}
                  onSubmit={compare}
                />
                {error && (
                  <p role="alert" className="error">
                    {error}
                  </p>
                )}
                <Chat
                  history={history}
                  enabled={llmOn}
                  maxChars={config.limits.message_chars}
                  onCanvas={applyCanvas}
                  onProfile={(p) => {
                    setProfile(p);
                    setProfileVersion((v) => v + 1);
                  }}
                  onLimit={(m) => setNotice(`${m} You can keep using the form.`)}
                />
              </div>
              <div className="right">
                <Canvas
                  canvas={canvas}
                  checklist={config.checklist}
                  estimateDisclaimer={config.estimate_disclaimer}
                  tab={tab}
                  onTab={setTab}
                  selected={selected}
                  onSelect={setSelected}
                />
                {ranked.length > 0 && (
                  <OutcomeCard planKeys={ranked.map((r) => ({ key: r.plan_key, name: r.plan_name }))} />
                )}
              </div>
            </div>
          )}
        </main>
        {feedbackOpen && <FeedbackDialog onClose={() => setFeedbackOpen(false)} lastToolCalls={[]} />}
        <Disclaimer />
      </div>
    </ModeContext.Provider>
  );
}
