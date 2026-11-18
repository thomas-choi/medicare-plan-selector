import type { Mode } from "./api";

interface Props {
  mode: Mode | null;
  onErase: () => void;
  onFeedback: () => void;
  onDownload: () => void;
  canDownload: boolean;
}

export function Header({ mode, onErase, onFeedback, onDownload, canDownload }: Props) {
  return (
    <header className="top">
      <h1>Medicare Plan Selector</h1>
      {mode && (
        <div className="header-actions">
          <span className={`badge ${mode}`} title="Session mode">
            {mode === "nosave" ? "No-save" : "Saved"}
          </span>
          <button onClick={onDownload} disabled={!canDownload}>
            Download comparison
          </button>
          <button onClick={onFeedback}>Feedback</button>
          <button className="danger" onClick={onErase}>
            {mode === "nosave" ? "End session & erase" : "Delete my data"}
          </button>
        </div>
      )}
    </header>
  );
}
