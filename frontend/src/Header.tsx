import type { Mode } from "./api";

interface Props {
  mode: Mode | null;
  onErase: () => void;
  onFeedback: () => void;
  onInfo: () => void;
  onDownloadCsv: () => void;
  onDownloadReport: () => void;
  canDownload: boolean;
}

export function Header({
  mode,
  onErase,
  onFeedback,
  onInfo,
  onDownloadCsv,
  onDownloadReport,
  canDownload,
}: Props) {
  return (
    <header className="top">
      <h1>Medicare Plan Selector</h1>
      {mode && (
        <div className="header-actions">
          <span className={`badge ${mode}`} title="Session mode">
            {mode === "nosave" ? "No-save" : "Saved"}
          </span>
          <button onClick={onInfo}>Important info</button>
          <button
            onClick={onDownloadCsv}
            disabled={!canDownload}
            title="Spreadsheet (.csv) of every plan, to sort and filter yourself"
          >
            Download comparison (.csv)
          </button>
          <button
            onClick={onDownloadReport}
            disabled={!canDownload}
            title="Readable report (.md) with the disclaimer, notes and checklist"
          >
            Download report
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
