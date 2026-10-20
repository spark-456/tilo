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
import { OfficePreview } from "../../results/OfficePreview";
import { type WebsiteArtifactVersion, WebsitePreview } from "../../results/WebsitePreview";
import { DirectionForm } from "./DirectionForm";

const OFFICE_MIME = "application/vnd.openxmlformats-officedocument.";
const OFFICE_TYPES: Readonly<Record<string, string>> = {
  DOCX: `${OFFICE_MIME}wordprocessingml.document`,
  XLSX: `${OFFICE_MIME}spreadsheetml.sheet`,
  PPTX: `${OFFICE_MIME}presentationml.presentation`,
};
const FILE_EXTENSIONS: Readonly<Record<string, string>> = {
  [OFFICE_TYPES.DOCX ?? ""]: ".docx",
  [OFFICE_TYPES.XLSX ?? ""]: ".xlsx",
  [OFFICE_TYPES.PPTX ?? ""]: ".pptx",
  "application/pdf": ".pdf",
  "text/csv": ".csv",
};

/** DOCS-OUT: the extension a delivered Word, Excel, PowerPoint, PDF or CSV file is saved with, from its type, else its format. */
function fileExtension(blob: Blob, format: string): string | undefined {
  const type = blob.type.split(";")[0]?.toLowerCase() ?? "";
  if (FILE_EXTENSIONS[type]) return FILE_EXTENSIONS[type];
  return /^(DOCX|XLSX|PPTX|PDF|CSV)$/.test(format) ? `.${format.toLowerCase()}` : undefined;
}

const readableMath = (text: string): string =>
  text.replace(/\$\\to\$/g, "→").replace(/\$([^$\n]+)\$/g, "$1");

function csvRows(raw: string): string[][] {
  const text = raw.replace(/^\uFEFF/, ""); // a CSV made for Excel starts with a byte-order mark
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
  const office =
    mime === OFFICE_TYPES.XLSX || format === "XLSX" || /\.xlsx$/i.test(name)
      ? "xlsx"
      : mime === OFFICE_TYPES.DOCX || format === "DOCX" || /\.docx$/i.test(name)
        ? "docx"
        : null;
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
    const previewType = OPEN_TYPES[format];
    const shown =
      blob.type === "application/octet-stream" &&
      (previewType?.startsWith("image/") || previewType === "application/pdf")
        ? new Blob([blob], { type: previewType })
        : blob;
    const url = URL.createObjectURL(shown);
    setImageUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [blob, format, image, pdf]);
  if (office) return <OfficePreview blob={blob} kind={office} />;
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
  readonly format: string | undefined;
  readonly mediaType: string | null;
  readonly who?: string;
  readonly size?: string;
  readonly color?: string;
}

const OPEN_TYPES: Readonly<Record<string, string>> = {
  ...OFFICE_TYPES,
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

function openableBlob(blob: Blob, file: DeliveredFile): Blob {
  if (blob.type !== "application/octet-stream") return blob;
  const extension = /\.([a-z0-9]+)$/i.exec(file.name)?.[1]?.toUpperCase();
  const recordedType = Object.values(OPEN_TYPES).includes(file.mediaType ?? "")
    ? file.mediaType
    : null;
  const type =
    OPEN_TYPES[extension ?? ""] ?? OPEN_TYPES[file.format?.toUpperCase() ?? ""] ?? recordedType;
  return type ? new Blob([blob], { type }) : blob;
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
  return cleaned.slice(0, 255) || null;
}

/** DEMO-DELIVER: the unit the Lead gave the agent that recorded a version ("The Lead gave it: <title>"), from events. */
function unitTitle(events: readonly RunEvent[], made: RunEvent | undefined): string | null {
  if (!made?.actor) return null;
  const assigned = [...events]
    .reverse()
    .find((e) => e.type === "agent.assigned" && e.target === made.actor && e.seq < made.seq);
  const title = assigned?.summary.match(/^The Lead gave it:\s*(.+?)\s*$/i)?.[1];
  return title ? safeDeliverableName(title) : null;
}

function recordedArtifact(
  events: readonly RunEvent[],
  id: string,
  version?: number,
): { label: string | null; mediaType: string | null; unit: string | null } {
  const recorded = [...events].reverse();
  const matches = (event: RunEvent, exactVersion: boolean) => {
    const data = event.data as
      | { artifact?: { artifact_id?: unknown; version?: unknown } }
      | undefined;
    return (
      (event.type === "artifact.created" || event.type === "artifact.versioned") &&
      data?.artifact?.artifact_id === id &&
      (!exactVersion || data.artifact.version === version)
    );
  };
  const made =
    recorded.find((event) => matches(event, true)) ??
    recorded.find((event) => matches(event, false));
  const item = made as (RunEvent & { item?: { label?: unknown } }) | undefined;
  const data = made?.data as { media_type?: unknown } | undefined;
  return {
    label: typeof item?.item?.label === "string" ? safeDeliverableName(item.item.label) : null,
    mediaType: typeof data?.media_type === "string" ? data.media_type : null,
    unit: unitTitle(events, made),
  };
}

function deliveredName(event: RunEvent, id: string, events: readonly RunEvent[]): string {
  const data = event.data as
    | { artifact?: { label?: unknown; version?: unknown }; format?: unknown; filename?: unknown }
    | undefined;
  if (typeof data?.filename === "string" && data.filename.trim()) {
    const filename = safeDeliverableName(data.filename);
    if (filename) return filename;
  }
  const label = data?.artifact?.label;
  const cleanLabel = typeof label === "string" ? safeDeliverableName(label) : null;
  if (cleanLabel && cleanLabel !== id) return cleanLabel;
  const version = typeof data?.artifact?.version === "number" ? data.artifact.version : undefined;
  const recorded = recordedArtifact(events, id, version);
  if (recorded.label) return recorded.label;
  const fromSummary = event.summary.match(
    /^(?:The |Your )?(.+?) (?:is ready|was delivered)(?: in Tilo)?\.?$/i,
  );
  const cleanSummary = fromSummary?.[1] ? safeDeliverableName(fromSummary[1]) : null;
  if (cleanSummary && !/^item$/i.test(cleanSummary)) return cleanSummary;
  const summary = /^The item was delivered\.?$/i.test(event.summary)
    ? null
    : safeDeliverableName(event.summary.replace(/[.!]+$/, ""));
  return (
    recorded.unit ??
    ((typeof data?.format === "string" && FORMAT_NAMES[data.format]) || summary || id)
  );
}

function extractDeliveredFiles(events: readonly RunEvent[]): DeliveredFile[] {
  const items: DeliveredFile[] = [];
  for (const e of events) {
    const data = e.data as
      | { artifact?: { artifact_id?: unknown; version?: unknown }; format?: unknown }
      | undefined;
    const id = data?.artifact?.artifact_id;
    if (
      e.type === "artifact.delivered" &&
      typeof id === "string" &&
      !items.some((x) => x.id === id)
    ) {
      const name = deliveredName(e, id, events);
      if (!items.some((x) => x.name.toLocaleLowerCase() === name.toLocaleLowerCase()))
        items.push({
          id,
          name,
          format: typeof data?.format === "string" ? data.format : undefined,
          mediaType: recordedArtifact(
            events,
            id,
            typeof data?.artifact?.version === "number" ? data.artifact.version : undefined,
          ).mediaType,
        });
    }
  }
  return items;
}

function getWebsiteArtifact(
  events: readonly RunEvent[],
  mainItem: DeliveredFile,
  _mainFormat: string,
): WebsiteArtifactVersion | null {
  const delivered = events.find((e) => e.type === "artifact.delivered");
  const data = delivered?.data as
    | { artifact?: { artifact_id?: unknown; version?: unknown }; format?: unknown }
    | undefined;
  const isWebsite = data?.format === "website" || mainItem.format === "website";
  if (!isWebsite) return null;
  const artifactId =
    (typeof data?.artifact?.artifact_id === "string" ? data.artifact.artifact_id : null) ??
    mainItem.id;
  const version = typeof data?.artifact?.version === "number" ? data.artifact.version : 1;
  const created = events.find(
    (e) =>
      (e.type === "artifact.created" || e.type === "artifact.versioned") &&
      (e.data as { artifact?: { artifact_id?: unknown } })?.artifact?.artifact_id === artifactId,
  );
  const createdData = created?.data as
    | { content_sha256?: unknown; media_type?: unknown }
    | undefined;
  const content_sha256 =
    typeof createdData?.content_sha256 === "string" ? createdData.content_sha256 : "";
  const media_type =
    typeof createdData?.media_type === "string" ? createdData.media_type : "text/html";
  return {
    artifact_id: artifactId,
    version,
    title: mainItem.name || "website",
    content_sha256,
    media_type,
  };
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
              onClick={() => readItem(f.id, (b) => openResult(openableBlob(b, f)))}
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
  const recordedMime = mainItem?.mediaType;
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
  const summary = mainEvent?.summary?.trim() ?? "";
  const mainSummary =
    summary && !/\bartifact\.(?:created|delivered|versioned)\b/i.test(summary)
      ? summary
      : "Ready to open or download.";

  const websiteArtifact = mainItem ? getWebsiteArtifact(events, mainItem, mainFormat) : null;
  const isWebsite = Boolean(websiteArtifact);
  const openLabel = isWebsite ? "Open full screen" : "Open result";
  const downloadLabel = isWebsite ? "Download as .html" : "Download";
  const copyLabel = isWebsite ? "Copy link" : "Copy";

  const handleOpen = () => {
    if (websiteArtifact) {
      const fsBtn = document.querySelector<HTMLButtonElement>(
        'button[aria-label="Open full screen"], button[aria-label="Exit full screen"]',
      );
      if (fsBtn) {
        fsBtn.click();
        return;
      }
    }
    if (blob && mainItem) openResult(openableBlob(blob, mainItem));
    else if (onOpen) onOpen();
  };

  const handleDownload = () => {
    if (blob) {
      if (isWebsite) {
        const filename = mainName.endsWith(".html") ? mainName : `${mainName}.html`;
        saveNamedResult(blob, filename);
      } else if (fileExtension(blob, mainFormat)) {
        const ext = fileExtension(blob, mainFormat) ?? "";
        saveNamedResult(
          blob,
          mainName.toLowerCase().endsWith(ext) ? mainName : `${mainName}${ext}`,
        );
      } else if (extension) {
        saveNamedResult(blob, mainName);
      } else {
        saveResult(blob, mainName);
      }
    } else if (onDownload) onDownload();
  };

  const handleCopy = async () => {
    try {
      if (isWebsite) {
        await navigator.clipboard.writeText(window.location.href);
        setActionStatus("Link copied");
        return;
      }
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

  return (
    <div className="tw-res-container" data-testid="result-tab">
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

          {websiteArtifact ? (
            <div className="tw-res-compat-body" data-testid="website-preview-wrapper">
              <WebsitePreview
                worldId={worldId}
                artifact={websiteArtifact}
                initialBlob={blob}
                isSignedIn={true}
              />
            </div>
          ) : view ? (
            <div className="tw-res-compat-body">
              <ResultBody view={view} retry={shared?.retry} name={mainName} format={mainFormat} />
            </div>
          ) : null}

          <div className="tw-res-actions">
            <button
              type="button"
              className="tw-res-btn tw-res-btn--pri"
              onClick={handleOpen}
              aria-label={openLabel}
            >
              <Icon name="eye" size={16} />
              {openLabel}
            </button>
            <button
              type="button"
              className="tw-res-btn tw-res-btn--sec"
              onClick={handleDownload}
              aria-label={downloadLabel}
            >
              <Icon name="download" size={16} />
              {downloadLabel}
            </button>
            <button
              type="button"
              className="tw-res-btn tw-res-btn--sec"
              onClick={handleCopy}
              aria-label={copyLabel}
            >
              <Icon name={isWebsite ? "link" : "copy"} size={16} />
              {copyLabel}
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

      {rawDelivered.length > 1 ? (
        <WorkingFiles api={api} worldId={worldId} items={rawDelivered.slice(1)} />
      ) : null}
    </div>
  );
}
