// Read the document body from a DOCX ZIP with browser APIs. Only text and structure reach React.
export interface DocRun {
  text: string;
  bold: boolean;
  italic: boolean;
}

export type DocBlock =
  | { kind: "paragraph"; level: number; runs: DocRun[] }
  | { kind: "table"; rows: string[][] };

const WORD_XML = "word/document.xml";
const XML_LIMIT = 1_500_000;

async function inflateDocument(compressed: Uint8Array): Promise<ArrayBuffer> {
  const reader = new Blob([compressed.buffer as ArrayBuffer])
    .stream()
    .pipeThrough(new DecompressionStream("deflate-raw"))
    .getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > XML_LIMIT) {
      await reader.cancel();
      throw new Error("Document is too large to preview");
    }
    chunks.push(value);
  }
  const result = new Uint8Array(length);
  let at = 0;
  for (const chunk of chunks) {
    result.set(chunk, at);
    at += chunk.byteLength;
  }
  return result.buffer;
}

async function documentXml(blob: Blob): Promise<string> {
  if (blob.size > 10_000_000) throw new Error("Document is too large to preview");
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const view = new DataView(bytes.buffer);
  let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65_557); i--) {
    if (view.getUint32(i, true) === 0x06054b50) {
      end = i;
      break;
    }
  }
  if (end < 0) throw new Error("Invalid document");
  let at = view.getUint32(end + 16, true);
  const count = Math.min(view.getUint16(end + 10, true), 2_000);
  for (let i = 0; i < count; i++) {
    if (at + 46 > bytes.length || view.getUint32(at, true) !== 0x02014b50)
      throw new Error("Invalid document");
    const method = view.getUint16(at + 10, true);
    const size = view.getUint32(at + 20, true);
    const expanded = view.getUint32(at + 24, true);
    const nameLength = view.getUint16(at + 28, true);
    const extraLength = view.getUint16(at + 30, true);
    const commentLength = view.getUint16(at + 32, true);
    const name = new TextDecoder().decode(bytes.subarray(at + 46, at + 46 + nameLength));
    if (name === WORD_XML) {
      if (expanded > XML_LIMIT) throw new Error("Document is too large to preview");
      const local = view.getUint32(at + 42, true);
      if (local + 30 > bytes.length || view.getUint32(local, true) !== 0x04034b50)
        throw new Error("Invalid document");
      const start =
        local + 30 + view.getUint16(local + 26, true) + view.getUint16(local + 28, true);
      if (start + size > bytes.length) throw new Error("Invalid document");
      const compressed = bytes.slice(start, start + size);
      const xml =
        method === 0 ? compressed.buffer : method === 8 ? await inflateDocument(compressed) : null;
      if (!xml || xml.byteLength > XML_LIMIT) throw new Error("Unsupported document");
      return new TextDecoder().decode(xml);
    }
    at += 46 + nameLength + extraLength + commentLength;
  }
  throw new Error("Document text is unavailable");
}

const nodeName = (element: Element): string => element.localName.split(":").at(-1) ?? "";
const descendantsNamed = (element: Document | Element, name: string): Element[] =>
  Array.from(element.getElementsByTagName("*")).filter((child) => nodeName(child) === name);
const childrenNamed = (element: Element, name: string): Element[] =>
  Array.from(element.children).filter((child) => nodeName(child) === name);

function paragraphRuns(paragraph: Element): DocRun[] {
  return descendantsNamed(paragraph, "r")
    .map((run) => ({
      text: Array.from(run.getElementsByTagName("*"))
        .filter((part) => ["t", "tab", "br"].includes(nodeName(part)))
        .map((part) =>
          nodeName(part) === "tab"
            ? "\t"
            : nodeName(part) === "br"
              ? "\n"
              : (part.textContent ?? ""),
        )
        .join(""),
      bold: descendantsNamed(run, "b").length > 0,
      italic: descendantsNamed(run, "i").length > 0,
    }))
    .filter((run) => run.text.length > 0);
}

export async function readDocx(blob: Blob): Promise<DocBlock[]> {
  const xml = new DOMParser().parseFromString(await documentXml(blob), "application/xml");
  if (xml.getElementsByTagName("parsererror").length) throw new Error("Invalid document text");
  const body = descendantsNamed(xml, "body")[0];
  if (!body) throw new Error("Document text is unavailable");
  const blocks: DocBlock[] = [];
  for (const part of Array.from(body.children).slice(0, 100)) {
    if (nodeName(part) === "p") {
      const runs = paragraphRuns(part);
      const style = descendantsNamed(part, "pStyle")[0];
      const heading = /Heading([1-3])/i.exec(
        style?.getAttribute("w:val") ?? style?.getAttribute("val") ?? "",
      );
      if (runs.length)
        blocks.push({ kind: "paragraph", level: heading ? Number(heading[1]) : 0, runs });
    } else if (nodeName(part) === "tbl") {
      const rows = childrenNamed(part, "tr").map((row) =>
        childrenNamed(row, "tc").map((cell) =>
          descendantsNamed(cell, "p")
            .map((p) =>
              paragraphRuns(p)
                .map((run) => run.text)
                .join(""),
            )
            .join("\n"),
        ),
      );
      if (rows.length) blocks.push({ kind: "table", rows });
    }
  }
  return blocks;
}
