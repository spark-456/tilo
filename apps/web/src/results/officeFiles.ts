// P0_DOCS_OUT: a read-only preview of Word and Excel files in the browser, with no library. An Office file is a zip of
// XML parts; this reads the few parts a preview needs (the central directory, then DEFLATE through the browser's
// DecompressionStream) and parses them with DOMParser. Nothing is run, fetched or inserted as markup: the result is
// plain text and numbers that React draws. Files and shown sizes are bounded.

export const MAX_PREVIEW_BYTES = 8 * 1024 * 1024;
export const MAX_PREVIEW_ROWS = 100;
export const MAX_PREVIEW_COLUMNS = 30;
const MAX_PART_BYTES = 16 * 1024 * 1024;
const MAX_DOC_BLOCKS = 400;

export type Inflate = (compressed: Uint8Array) => Promise<Uint8Array>;

/** Browser inflate of a raw DEFLATE stream. */
export const inflateRaw: Inflate = async (compressed) => {
  const stream = new Blob([compressed as BlobPart])
    .stream()
    .pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
};

interface ZipEntry {
  readonly method: number;
  readonly compressedSize: number;
  readonly size: number;
  readonly offset: number;
}

function entriesOf(bytes: Uint8Array): Map<string, ZipEntry> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 22 - 65_535); i--) {
    if (view.getUint32(i, true) === 0x06054b50) {
      end = i;
      break;
    }
  }
  if (end < 0) throw new Error("not a zip file");
  const count = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  const decoder = new TextDecoder();
  const found = new Map<string, ZipEntry>();
  for (let n = 0; n < count && n < 2000; n++) {
    if (view.getUint32(at, true) !== 0x02014b50) throw new Error("bad zip directory");
    const nameLength = view.getUint16(at + 28, true);
    const extraLength = view.getUint16(at + 30, true);
    const commentLength = view.getUint16(at + 32, true);
    found.set(decoder.decode(bytes.subarray(at + 46, at + 46 + nameLength)), {
      method: view.getUint16(at + 10, true),
      compressedSize: view.getUint32(at + 20, true),
      size: view.getUint32(at + 24, true),
      offset: view.getUint32(at + 42, true),
    });
    at += 46 + nameLength + extraLength + commentLength;
  }
  return found;
}

class Zip {
  private constructor(
    private readonly bytes: Uint8Array,
    private readonly entries: Map<string, ZipEntry>,
    private readonly inflate: Inflate,
  ) {}

  static async open(blob: Blob, inflate: Inflate): Promise<Zip> {
    if (blob.size > MAX_PREVIEW_BYTES) throw new Error("too large to preview");
    const bytes = new Uint8Array(await blob.arrayBuffer());
    return new Zip(bytes, entriesOf(bytes), inflate);
  }

  has(name: string): boolean {
    return this.entries.has(name);
  }

  async text(name: string): Promise<string | null> {
    const entry = this.entries.get(name);
    if (!entry) return null;
    if (entry.size > MAX_PART_BYTES) throw new Error("part too large to preview");
    const view = new DataView(this.bytes.buffer, this.bytes.byteOffset, this.bytes.byteLength);
    const start =
      entry.offset +
      30 +
      view.getUint16(entry.offset + 26, true) +
      view.getUint16(entry.offset + 28, true);
    const data = this.bytes.subarray(start, start + entry.compressedSize);
    const raw = entry.method === 0 ? data : entry.method === 8 ? await this.inflate(data) : null;
    if (!raw || raw.length > MAX_PART_BYTES) throw new Error("unsupported part");
    return new TextDecoder().decode(raw);
  }
}

const parse = (xml: string): Element => {
  const bare = xml.replace(/^﻿?\s*<\?xml[^>]*\?>/, ""); // the declaration says nothing a preview needs
  const root = new DOMParser().parseFromString(bare, "application/xml").documentElement;
  if (!root || root.localName === "parsererror" || root.querySelector("parsererror"))
    throw new Error("unreadable part");
  return root;
};

/** Every descendant element with this local name (namespace prefixes differ between writers). */
const all = (root: Element, name: string): Element[] =>
  Array.from(root.getElementsByTagName("*")).filter((el) => el.localName === name);

const child = (root: Element, name: string): Element | undefined =>
  Array.from(root.children).find((el) => el.localName === name);

const attr = (el: Element | undefined, name: string): string =>
  el?.getAttribute(name) ?? el?.getAttribute(`w:${name}`) ?? "";

// ---- Excel ---------------------------------------------------------------------------------------------------------

export interface SheetPreview {
  readonly sheets: readonly string[];
  readonly shown: number;
  readonly rows: readonly (readonly string[])[];
  readonly moreRows: boolean;
  readonly moreColumns: boolean;
}

const BUILT_IN_DATES = new Set([14, 15, 16, 17, 22, 27, 30, 36, 45, 46, 47, 50, 57]);

function columnIndex(ref: string): number {
  let n = 0;
  for (const ch of ref.replace(/[0-9]/g, "")) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n - 1;
}

function dateFlags(styles: Element | undefined): boolean[] {
  if (!styles) return [];
  const formats = new Map<number, string>();
  for (const f of all(styles, "numFmt"))
    formats.set(Number(attr(f, "numFmtId")), attr(f, "formatCode"));
  const xfs = child(styles, "cellXfs");
  return xfs
    ? Array.from(xfs.children).map((xf) => {
        const id = Number(attr(xf, "numFmtId"));
        const code = (formats.get(id) ?? "").replace(/"[^"]*"|\[[^\]]*\]|\\./g, "");
        return BUILT_IN_DATES.has(id) || /[ymd]/i.test(code.replace(/[#0.,?]/g, ""));
      })
    : [];
}

function shown(value: number): string {
  return Number.isInteger(value)
    ? value.toLocaleString("en-US")
    : value.toLocaleString("en-US", { maximumFractionDigits: 10 });
}

export async function previewXlsx(
  blob: Blob,
  sheetIndex = 0,
  inflate: Inflate = inflateRaw,
): Promise<SheetPreview> {
  const zip = await Zip.open(blob, inflate);
  const workbook = parse((await zip.text("xl/workbook.xml")) ?? "");
  const sheetNodes = all(workbook, "sheet");
  const sheets = sheetNodes.map((s) => attr(s, "name"));
  const at = Math.min(Math.max(sheetIndex, 0), sheetNodes.length - 1);
  const relId = sheetNodes[at]?.getAttribute("r:id") ?? "";
  const rels = parse((await zip.text("xl/_rels/workbook.xml.rels")) ?? "");
  const target = all(rels, "Relationship")
    .find((r) => r.getAttribute("Id") === relId)
    ?.getAttribute("Target");
  if (!target) throw new Error("no such sheet");
  const path = target.startsWith("/") ? target.slice(1) : `xl/${target}`;
  const strings = zip.has("xl/sharedStrings.xml")
    ? all(parse((await zip.text("xl/sharedStrings.xml")) ?? ""), "si").map((si) =>
        all(si, "t")
          .map((t) => t.textContent ?? "")
          .join(""),
      )
    : [];
  const dates = dateFlags(
    zip.has("xl/styles.xml") ? parse((await zip.text("xl/styles.xml")) ?? "") : undefined,
  );
  const rows: string[][] = [];
  let moreColumns = false;
  const sheetRows = all(parse((await zip.text(path)) ?? ""), "row");
  for (const row of sheetRows.slice(0, MAX_PREVIEW_ROWS + 1)) {
    const cells: string[] = [];
    for (const c of Array.from(row.children).filter((el) => el.localName === "c")) {
      const index = columnIndex(c.getAttribute("r") ?? "");
      if (index >= MAX_PREVIEW_COLUMNS) {
        moreColumns = true;
        continue;
      }
      const raw = child(c, "v")?.textContent ?? "";
      const kind = c.getAttribute("t");
      let text = raw;
      if (kind === "s") text = strings[Number(raw)] ?? "";
      else if (kind === "inlineStr")
        text = all(c, "t")
          .map((t) => t.textContent ?? "")
          .join("");
      else if (kind === "b") text = raw === "1" ? "TRUE" : "FALSE";
      else if (raw !== "" && kind !== "str" && kind !== "e" && Number.isFinite(Number(raw))) {
        const serial = Number(raw);
        text = dates[Number(c.getAttribute("s") ?? "0")]
          ? new Date(Math.round((serial - 25569) * 86_400_000)).toISOString().slice(0, 10)
          : shown(serial);
      }
      while (cells.length < index) cells.push("");
      cells[index] = text;
    }
    rows.push(cells);
  }
  return {
    sheets,
    shown: at,
    rows: rows.slice(0, MAX_PREVIEW_ROWS + 1),
    moreRows: sheetRows.length > MAX_PREVIEW_ROWS + 1,
    moreColumns,
  };
}

// ---- Word ----------------------------------------------------------------------------------------------------------

export type DocBlock =
  | { readonly kind: "title" | "subtitle" | "h1" | "h2" | "p" | "li"; readonly text: string }
  | { readonly kind: "table"; readonly rows: readonly (readonly string[])[] }
  | { readonly kind: "chart" };

export interface DocPreview {
  readonly blocks: readonly DocBlock[];
  readonly more: boolean;
}

const KINDS: Readonly<Record<string, "title" | "subtitle" | "h1" | "h2" | "li">> = {
  title: "title",
  subtitle: "subtitle",
  heading1: "h1",
  heading2: "h2",
  heading3: "h2",
  listbullet: "li",
  listparagraph: "li",
  listnumber: "li",
};

const paragraphText = (p: Element): string =>
  all(p, "t")
    .map((t) => t.textContent ?? "")
    .join("");

export async function previewDocx(blob: Blob, inflate: Inflate = inflateRaw): Promise<DocPreview> {
  const zip = await Zip.open(blob, inflate);
  const body = child(parse((await zip.text("word/document.xml")) ?? ""), "body");
  if (!body) throw new Error("no document body");
  const blocks: DocBlock[] = [];
  let more = false;
  for (const node of Array.from(body.children)) {
    if (blocks.length >= MAX_DOC_BLOCKS) {
      more = true;
      break;
    }
    if (node.localName === "tbl") {
      const rows = Array.from(node.children)
        .filter((tr) => tr.localName === "tr")
        .slice(0, MAX_PREVIEW_ROWS + 1)
        .map((tr) =>
          Array.from(tr.children)
            .filter((tc) => tc.localName === "tc")
            .slice(0, MAX_PREVIEW_COLUMNS)
            .map((tc) => all(tc, "p").map(paragraphText).join("\n")),
        );
      blocks.push({ kind: "table", rows });
    } else if (node.localName === "p") {
      if (all(node, "chart").length > 0) blocks.push({ kind: "chart" });
      const text = paragraphText(node);
      if (!text.trim()) continue;
      const style = attr(all(node, "pStyle")[0], "val").toLowerCase().replace(/[\s-]/g, "");
      blocks.push({ kind: KINDS[style] ?? "p", text });
    }
  }
  return { blocks, more };
}
