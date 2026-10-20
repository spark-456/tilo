// P0_DOCS_OUT: the Result tab's read-only preview of a Word or Excel file. Everything shown is text read from the file
// itself (never markup); a file that cannot be read says so and still offers Open and Download.
import { useEffect, useState } from "react";
import {
  type DocPreview,
  MAX_PREVIEW_ROWS,
  type SheetPreview,
  previewDocx,
  previewXlsx,
} from "./officeFiles";

type Loaded =
  | { readonly status: "loading" }
  | { readonly status: "error" }
  | { readonly status: "xlsx"; readonly view: SheetPreview }
  | { readonly status: "docx"; readonly view: DocPreview };

const FALLBACK = "Open or download this file to read it.";

function Grid({ rows }: { rows: readonly (readonly string[])[] }) {
  const [head = [], ...body] = rows;
  const width = Math.max(head.length, ...body.map((row) => row.length));
  const cells = (row: readonly string[]) => Array.from({ length: width }, (_, i) => row[i] ?? "");
  return (
    <table>
      <thead>
        <tr>
          {cells(head).map((cell, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: a column is its position
            <th key={index} scope="col">
              {cell}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {body.slice(0, MAX_PREVIEW_ROWS).map((row, r) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: a row is its position
          <tr key={r}>
            {cells(row).map((cell, c) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: a cell is its position
              <td key={c}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function OfficePreview({ blob, kind }: { blob: Blob; kind: "docx" | "xlsx" }) {
  const [sheet, setSheet] = useState(0);
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });
  useEffect(() => {
    let live = true;
    setLoaded({ status: "loading" });
    const done = (next: Loaded) => live && setLoaded(next);
    (kind === "xlsx"
      ? previewXlsx(blob, sheet).then((view) => done({ status: "xlsx", view }))
      : previewDocx(blob).then((view) => done({ status: "docx", view }))
    ).catch(() => done({ status: "error" }));
    return () => {
      live = false;
    };
  }, [blob, kind, sheet]);

  if (loaded.status === "loading") return <p className="park-world-noruns">Loading preview…</p>;
  if (loaded.status === "error") return <p className="park-world-noruns">{FALLBACK}</p>;
  if (loaded.status === "xlsx") {
    const { view } = loaded;
    return (
      <div className="tw-res-preview" data-testid="result-preview" data-kind="xlsx">
        {view.sheets.length > 1 ? (
          <div className="tw-res-sheets" role="tablist" aria-label="Sheets">
            {view.sheets.map((name, index) => (
              <button
                // biome-ignore lint/suspicious/noArrayIndexKey: sheet names can repeat in a broken file; the position is the identity
                key={index}
                type="button"
                role="tab"
                aria-selected={index === view.shown}
                className="tw-res-sheet-tab"
                onClick={() => setSheet(index)}
              >
                {name}
              </button>
            ))}
          </div>
        ) : null}
        <Grid rows={view.rows} />
        {view.moreRows || view.moreColumns ? (
          <p className="park-world-sub">
            Showing the start of this sheet. Download it for the rest.
          </p>
        ) : null}
      </div>
    );
  }
  const { blocks, more } = loaded.view;
  return (
    <div className="tw-res-preview tw-res-doc" data-testid="result-preview" data-kind="docx">
      {blocks.map((block, index) => {
        const key = `${index}:${block.kind}`;
        if (block.kind === "table") return <Grid key={key} rows={block.rows} />;
        if (block.kind === "chart")
          return (
            <p key={key} className="park-world-sub">
              A chart is in the file.
            </p>
          );
        if (block.kind === "title") return <h3 key={key}>{block.text}</h3>;
        if (block.kind === "h1") return <h4 key={key}>{block.text}</h4>;
        if (block.kind === "h2") return <h5 key={key}>{block.text}</h5>;
        if (block.kind === "li")
          return <p key={key} className="tw-res-doc-li">{`• ${block.text}`}</p>;
        return (
          <p key={key} className={block.kind === "subtitle" ? "park-world-sub" : undefined}>
            {block.text}
          </p>
        );
      })}
      {more ? <p className="park-world-sub">Showing the start. Download it for the rest.</p> : null}
    </div>
  );
}
