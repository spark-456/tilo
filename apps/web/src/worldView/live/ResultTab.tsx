// TILO-W: Result tab with rich previews, working files accordion, and where it was made
// (design/tilo-w PROMPT.md, Tilo W Parts.dc.html lines 253-365).
import type React from "react";
import { useEffect, useState } from "react";
import { Icon, type IconName } from "../../design/tilo-t";
import type { Api } from "../../park/api";
import { openResult, readResult, saveNamedResult, saveResult } from "../../park/api/results";
import type { SharedResult } from "../../park/pages/World/ResultPanel";
import { Markdown } from "../../park/pages/World/markdown";
import type { RunEvent } from "../../park/pages/World/useRunEvents";
import type { ResultView } from "../../park/pages/World/useRunResult";
import { DirectionForm } from "./DirectionForm";

const readableMath = (text: string): string =>
  text.replace(/\$\\to\$/g, "→").replace(/\$([^$\n]+)\$/g, "$1");

function csvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = !quoted;
    } else if (char === "," && !quoted) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      if (char === "\r" && text[i + 1] === "\n") i++;
      if (rows.length >= 101) break;
    } else cell += char;
  }
  if (cell || row.length) rows.push([...row, cell]);
  return rows;
}

function FilePreview({ blob, name, format }: { blob: Blob; name: string; format: string }) {
  const mime = blob.type.split(";")[0]?.toLowerCase();
  const csv = mime === "text/csv" || format === "CSV" || /\.csv$/i.test(name);
  const html = mime === "text/html" || format === "HTML" || /\.html?$/i.test(name);
  const markdown = mime === "text/markdown" || format === "MD" || /\.md$/i.test(name);
  const plain = mime === "text/plain" || format === "TXT" || /\.txt$/i.test(name);
  const pdf = mime === "application/pdf" || format === "PDF" || /\.pdf$/i.test(name);
  const image =
    mime?.startsWith("image/") ||
    /^(PNG|JPG|JPEG|WEBP|GIF)$/.test(format) ||
    /\.(png|jpe?g|webp|gif)$/i.test(name);
  const [text, setText] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!csv && !html && !markdown && !plain) return;
    let active = true;
    blob
      .slice(0, 250_000)
      .text()
      .then((value) => {
        if (active) setText(value);
      });
    return () => {
      active = false;
    };
  }, [blob, csv, html, markdown, plain]);
  useEffect(() => {
    if (!image && !pdf) return;
    const url = URL.createObjectURL(blob);
    setImageUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [blob, image, pdf]);
  if (csv && text !== null) {
    const [head = [], ...body] = csvRows(text);
    return (
      <div className="tw-res-preview" data-testid="result-preview">
        <table>
          <thead>
            <tr>
              {head.map((cell, index) => (
                <th key={`${index}:${cell}`} scope="col">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.slice(0, 100).map((row, index) => (
              <tr key={`row-${index}:${row.join("|")}`}>
                {row.map((cell, column) => (
                  <td key={`${column}:${cell}`}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {body.length > 100 ? <p>Showing the first 100 rows. Download for the rest.</p> : null}
      </div>
    );
  }
  if (html && text !== null)
    return (
      <div className="tw-res-preview" data-testid="result-preview">
        <iframe
          title={`Preview of ${name}`}
          sandbox=""
          referrerPolicy="no-referrer"
          srcDoc={`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:">${text}`}
        />
      </div>
    );
  if (markdown && text !== null)
    return (
      <div className="park-world-resulttext tw-res-preview" data-testid="result-preview">
        <Markdown text={readableMath(text)} />
      </div>
    );
  if (plain && text !== null)
    return (
      <div className="park-world-resulttext tw-res-preview" data-testid="result-preview">
        <pre className="park-world-resultpre">{readableMath(text)}</pre>
      </div>
    );
  if (pdf && imageUrl)
    return (
      <div className="tw-res-preview" data-testid="result-preview">
        <iframe title={`Preview of ${name}`} src={imageUrl} referrerPolicy="no-referrer" />
      </div>
    );
  if (image && imageUrl)
    return (
      <div className="tw-res-preview" data-testid="result-preview">
        <img src={imageUrl} alt={name} />
      </div>
    );
  if ((csv || html || markdown || plain) && text === null)
    return <p className="park-world-noruns">Loading preview…</p>;
  if ((image || pdf) && !imageUrl) return <p className="park-world-noruns">Loading preview…</p>;
  return <p className="park-world-noruns">Open or download this file to read it.</p>;
}

function ResultBody({
  view,
  retry,
  name,
  format,
}: { view: ResultView; retry?: () => void; name: string; format: string }) {
  if (view.status === "loading") return <p className="park-world-noruns">Loading the result…</p>;
  if (view.status === "error")
    return (
      <div role="alert">
        <p className="park-world-noruns">The result could not be loaded. Nothing is lost.</p>
        {retry ? (
          <button
            type="button"
            className="park-btn park-btn--secondary park-btn--sm"
            onClick={retry}
          >
            Try again
          </button>
        ) : null}
      </div>
    );
  if (view.status === "file") return <FilePreview blob={view.blob} name={name} format={format} />;
  if (view.status !== "text") return null;
  return (
    // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrolling text box must be reachable by keyboard to be read
    <div className="park-world-resulttext tw-res-preview" data-testid="result-text" tabIndex={0}>
      {view.kind === "markdown" ? (
        <Markdown text={readableMath(view.text)} />
      ) : (
        <pre className="park-world-resultpre">{readableMath(view.text)}</pre>
      )}
      {view.cut ? (
        <p className="park-world-sub">Showing the start. Download it for the rest.</p>
      ) : null}
    </div>
  );
}

interface DeliveredFile {
  readonly id: string;
  readonly name: string;
  readonly who?: string;
  readonly size?: string;
  readonly color?: string;
}

const FORMAT_NAMES: Record<string, string> = {
  pdf: "Document",
  docx: "Document",
  xlsx: "Spreadsheet",
  csv: "Spreadsheet",
  md: "Notes",
  txt: "Text",
};

function safeDeliverableName(raw: string): string | null {
  const trimmed = raw.trim();
  const cleaned = trimmed.replace(/[<>:"/\\|?*\p{Cc}]/gu, " ").replace(/\s+/g, " ");
  return cleaned.slice(0, 80) || null;
}

function recordedArtifact(
  events: readonly RunEvent[],
  id: string,
): { label: string | null; mediaType: string | null } {
  const made = events.find((event) => {
    const data = event.data as { artifact?: { artifact_id?: unknown } } | undefined;
    return (
      (event.type === "artifact.created" || event.type === "artifact.versioned") &&
      data?.artifact?.artifact_id === id
    );
  });
  const item = made as (RunEvent & { item?: { label?: unknown } }) | undefined;
  const data = made?.data as { media_type?: unknown } | undefined;
  return {
    label: typeof item?.item?.label === "string" ? safeDeliverableName(item.item.label) : null,
    mediaType: typeof data?.media_type === "string" ? data.media_type : null,
  };
}

function deliveredName(event: RunEvent, id: string, events: readonly RunEvent[]): string {
  const data = event.data as
    | { artifact?: { label?: unknown }; format?: unknown; filename?: unknown }
    | undefined;
  if (typeof data?.filename === "string" && data.filename.trim()) {
    const filename = safeDeliverableName(data.filename);
    if (filename) return filename;
  }
  const label = data?.artifact?.label;
  const cleanLabel = typeof label === "string" ? safeDeliverableName(label) : null;
  if (cleanLabel && cleanLabel !== id) return cleanLabel;
  const recordedLabel = recordedArtifact(events, id).label;
  if (recordedLabel) return recordedLabel;
  const fromSummary = event.summary.match(
    /^(?:The |Your )?(.+?) (?:is ready|was delivered)(?: in Tilo)?\.?$/i,
  );
  const cleanSummary = fromSummary?.[1] ? safeDeliverableName(fromSummary[1]) : null;
  if (cleanSummary && !/^item$/i.test(cleanSummary)) return cleanSummary;
  const summary = /^The item was delivered\.?$/i.test(event.summary)
    ? null
    : safeDeliverableName(event.summary.replace(/[.!]+$/, ""));
  return (typeof data?.format === "string" && FORMAT_NAMES[data.format]) || summary || id;
}

function extractDeliveredFiles(events: readonly RunEvent[]): DeliveredFile[] {
  const items: DeliveredFile[] = [];
  for (const e of events) {
    const data = e.data as { artifact?: { artifact_id?: unknown } } | undefined;
    const id = data?.artifact?.artifact_id;
    if (
      e.type === "artifact.delivered" &&
      typeof id === "string" &&
      !items.some((x) => x.id === id)
    ) {
      const name = deliveredName(e, id, events);
      if (!items.some((x) => x.name.toLocaleLowerCase() === name.toLocaleLowerCase()))
        items.push({ id, name });
    }
  }
  return items;
}

export interface ResultTabProps {
  readonly api?: Api;
  readonly worldId: string;
  readonly events?: readonly RunEvent[];
  readonly shared?: SharedResult;
  readonly onOpen?: () => void;
  readonly onDownload?: () => void;
  readonly onShare?: () => void;
  readonly onAskQuestion?: () => void;
  readonly onChangeDirection?: (instruction: string) => Promise<void>;
}

function WorkingFiles({
  api,
  worldId,
  items,
}: {
  api?: Api | undefined;
  worldId: string;
  items: readonly DeliveredFile[];
}) {
  const [loadError, setLoadError] = useState(false);
  const readItem = (id: string, use: (b: Blob) => void) => {
    if (!api) return;
    setLoadError(false);
    readResult(api, worldId, id).then(use, () => setLoadError(true));
  };
  return (
    <details data-testid="working-files" className="tw-res-files tw-res-slide-4">
      <summary className="tw-res-files-summary">
        <span className="tw-res-files-summary__icon" aria-hidden="true">
          <Icon name="file" size={18} />
        </span>
        <span className="tw-res-files-summary__text">
          <span className="tw-res-files-summary__title">{`Working files (${items.length})`}</span>
          <span className="tw-res-files-summary__sub">
            {items[0]?.name
              ? `${items[0].name}${items.length > 1 ? ` and ${items.length - 1} more` : ""}`
              : "What the agents made along the way"}
          </span>
        </span>
        <span className="tw-res-files-summary__chev" aria-hidden="true">
          <Icon name="chevD" size={16} />
        </span>
      </summary>

      <ul className="tw-res-files-list">
        {items.map((f) => (
          <li key={f.id} className="tw-res-files__item park-world-resultactions">
            <span className="tw-res-files__dot" data-ag="ag3" />
            <span className="tw-res-files__name park-world-sub">{f.name}</span>
            <button
              type="button"
              className="tw-res-file-btn tw-res-file-btn--icon secondary"
              aria-label={`Open working file: ${f.name}`}
              title={`Open ${f.name}`}
              onClick={() => readItem(f.id, openResult)}
            >
              <Icon name="eye" size={16} />
              <span className="park-sr-only">{`Open working file: ${f.name}`}</span>
            </button>
            <button
              type="button"
              className="tw-res-file-btn tw-res-file-btn--icon secondary"
              aria-label={`Download working file: ${f.name}`}
              title={`Download ${f.name}`}
              onClick={() => readItem(f.id, (b) => saveNamedResult(b, f.name))}
            >
              <Icon name="download" size={16} />
              <span className="park-sr-only">{`Download working file: ${f.name}`}</span>
            </button>
          </li>
        ))}
      </ul>
      {loadError ? (
        <p className="park-world-noruns" role="alert">
          That item could not be loaded. Nothing is lost. Try opening or downloading it again.
        </p>
      ) : null}
    </details>
  );
}

export function ResultTab({
  api,
  worldId,
  events = [],
  shared,
  onOpen,
  onDownload,
  onShare,
  onAskQuestion,
  onChangeDirection,
}: ResultTabProps) {
  const [directionOpen, setDirectionOpen] = useState(false);
  const [actionStatus, setActionStatus] = useState("");
  const rawDelivered = extractDeliveredFiles(events);
  const view = shared?.view;
  const blob = view && (view.status === "text" || view.status === "file") ? view.blob : null;

  if (rawDelivered.length === 0)
    return (
      <div className="tw-res-container" data-testid="result-tab">
        <p className="park-world-noruns">Nothing delivered yet.</p>
      </div>
    );

  const mainItem = rawDelivered[0];
  const mainName =
    mainItem?.name ??
    (view?.status === "text"
      ? view.text
          .trim()
          .split("\n")[0]
          ?.replace(/^#*\s*/, "") || "Result"
      : "Result");
  const mainEvent = events.find((event) => event.type === "artifact.delivered");
  const mainData = mainEvent?.data as { format?: unknown } | undefined;
  const declaredFormat = typeof mainData?.format === "string" ? mainData.format.toUpperCase() : "";
  const extension = /\.([a-z0-9]+)$/i.exec(mainName)?.[1]?.toUpperCase();
  const recordedMime = mainItem ? recordedArtifact(events, mainItem.id).mediaType : null;
  const mime = blob?.type !== "application/octet-stream" ? blob?.type : recordedMime;
  const mimeFormat =
    mime === "text/markdown"
      ? "MD"
      : mime === "text/csv"
        ? "CSV"
        : mime === "text/html"
          ? "HTML"
          : mime?.startsWith("image/")
            ? mime.slice(6).toUpperCase()
            : "";
  const mainFormat =
    extension ||
    (declaredFormat !== "IN_APP" && declaredFormat !== "" ? declaredFormat : mimeFormat) ||
    "FILE";
  const typeIcon: IconName =
    mainFormat === "CSV" || mainFormat === "XLSX"
      ? "sheet"
      : mainFormat === "HTML"
        ? "browser"
        : /^(PNG|JPG|JPEG|WEBP|GIF)$/.test(mainFormat)
          ? "palette"
          : "file";
  const mainSummary = mainEvent?.summary || "Ready to open or download.";

  const handleOpen = () => {
    const browserType: Record<string, string> = {
      PDF: "application/pdf",
      CSV: "text/csv",
      HTML: "text/html",
      MD: "text/markdown",
      TXT: "text/plain",
      PNG: "image/png",
      JPG: "image/jpeg",
      JPEG: "image/jpeg",
      WEBP: "image/webp",
      GIF: "image/gif",
    };
    if (blob)
      openResult(
        blob.type === "application/octet-stream" && browserType[mainFormat]
          ? new Blob([blob], { type: browserType[mainFormat] })
          : blob,
      );
    else if (onOpen) onOpen();
  };

  const handleDownload = () => {
    if (blob) saveResult(blob, mainName);
    else if (onDownload) onDownload();
  };

  const handleCopy = async () => {
    try {
      const content =
        view?.status === "text"
          ? view.text
          : blob && (/^(CSV|HTML|MD|TXT)$/.test(mainFormat) || blob.type.startsWith("text/"))
            ? await blob.text()
            : document.URL;
      if (!content) throw new Error("Nothing to copy");
      await navigator.clipboard.writeText(content);
      setActionStatus("Copied");
    } catch {
      setActionStatus("Copy unavailable here");
    }
  };

  const handleShare = async () => {
    if (onShare) {
      onShare();
      return;
    }
    try {
      await navigator.clipboard.writeText(document.URL);
      setActionStatus("Link copied");
    } catch {
      setActionStatus("Share link unavailable here");
    }
  };

  const lastDeliveryEvent = [...events].reverse().find((e) => e.type === "artifact.delivered");
  const deliveryTime = lastDeliveryEvent
    ? new Date(lastDeliveryEvent.ts)
        .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
        .toLowerCase()
    : "";
  const piecesCount = rawDelivered.length;

  return (
    <div className="tw-res-container" data-testid="result-tab">
      {/* 1. Delivered to the Dock Banner */}
      <div className="tw-res-del tw-res-slide-0" data-testid="delivered-banner">
        <span className="tw-res-del__icon" aria-hidden="true">
          <Icon name="parcel" size={18} />
        </span>
        <span className="tw-res-del__meta">
          <span className="tw-res-del__title">Delivered to the Dock</span>
          <span className="tw-res-del__sub">
            artifact.delivered · {deliveryTime} · {piecesCount} pieces
          </span>
        </span>
      </div>

      {/* 2. Main Deliverable Card */}
      <div className="tw-res-card tw-res-card--main tw-res-slide-1" data-testid="run-result">
        <div className="tw-res-body">
          <div className="tw-res-meta-line">
            <span className="tw-res-type-pill" data-type={mainFormat}>
              <Icon name={typeIcon} size={15} />
              {mainFormat}
            </span>
            <span className="tw-res-meta">Made in Tilo</span>
          </div>

          <h2 className="tw-res-title">{mainName}</h2>
          <p className="tw-res-summary">{mainSummary}</p>

          {view ? (
            <div className="tw-res-compat-body">
              <ResultBody view={view} retry={shared?.retry} name={mainName} format={mainFormat} />
            </div>
          ) : null}

          <div className="tw-res-actions">
            <button type="button" className="tw-res-btn tw-res-btn--pri" onClick={handleOpen}>
              <Icon name="eye" size={16} />
              Open result
            </button>
            <button type="button" className="tw-res-btn tw-res-btn--sec" onClick={handleDownload}>
              <Icon name="download" size={16} />
              Download
            </button>
            <button type="button" className="tw-res-btn tw-res-btn--sec" onClick={handleCopy}>
              <Icon name="copy" size={16} />
              Copy
            </button>
            <button type="button" className="tw-res-btn tw-res-btn--sec" onClick={handleShare}>
              <Icon name="link" size={16} />
              Share
            </button>
          </div>
          {actionStatus ? <output className="park-world-sub">{actionStatus}</output> : null}

          {onAskQuestion || onChangeDirection ? (
            <div className="tw-res-followup">
              <strong>Want to follow up?</strong>
              <div className="tw-res-followup__actions">
                {onAskQuestion ? (
                  <button
                    type="button"
                    className="tw-res-btn tw-res-btn--sec"
                    onClick={onAskQuestion}
                  >
                    Ask a question
                  </button>
                ) : null}
                {onChangeDirection ? (
                  <button
                    type="button"
                    className="tw-res-btn tw-res-btn--sec"
                    aria-expanded={directionOpen}
                    onClick={() => setDirectionOpen((open) => !open)}
                  >
                    Change direction
                  </button>
                ) : null}
              </div>
              {directionOpen && onChangeDirection ? (
                <DirectionForm
                  onStart={onChangeDirection}
                  onCancel={() => setDirectionOpen(false)}
                />
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      {/* 4. Folded Working Files */}
      {rawDelivered.length > 1 ? (
        <WorkingFiles api={api} worldId={worldId} items={rawDelivered.slice(1)} />
      ) : null}

      {/* 5. Where it was made */}
      <div className="tw-res-made tw-res-slide-5" data-testid="where-it-was-made">
        <span className="tw-res-made__header">WHERE IT WAS MADE</span>
        <div className="tw-res-made__grid">
          <div className="tw-res-made__card">
            <span className="tw-res-made__icon" aria-hidden="true">
              <Icon name="sparkle" size={18} />
            </span>
            <span className="tw-res-made__name">Tilo</span>
            <span className="tw-res-made__desc">{`${piecesCount} delivered ${piecesCount === 1 ? "file" : "files"}`}</span>
          </div>
        </div>
        <p className="tw-res-made__later">Other services coming later.</p>
      </div>
    </div>
  );
}
