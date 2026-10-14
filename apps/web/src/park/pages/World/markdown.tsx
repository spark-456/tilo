// WORLD-USEFUL: the delivered text of a run, readable on the page. A small renderer for the markdown a model
// writes (headings, lists, tables, fenced code, bold, code spans, https links), built as React elements: no HTML
// string is ever set, so a result can never inject markup. Anything it does not know stays plain text.
import { type ReactNode, createElement } from "react";

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${i}:${part.slice(0, 12)}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return <code key={key}>{part.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(part);
    if (link)
      return (
        <a key={key} href={link[2]} target="_blank" rel="noopener noreferrer">
          {link[1]}
        </a>
      );
    return part;
  });
}

const cells = (row: string): string[] =>
  row
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());

/** The blocks of a markdown text, as elements. */
export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  const next = (): string => lines[i] ?? "";
  while (i < lines.length) {
    const line = next();
    const at = `b${out.length}`;
    if (line.trim() === "") {
      i++;
    } else if (line.startsWith("```")) {
      const code: string[] = [];
      for (i++; i < lines.length && !next().startsWith("```"); i++) code.push(next());
      i++;
      out.push(<pre key={at}>{code.join("\n")}</pre>);
    } else if (/^#{1,6}\s/.test(line)) {
      const level = Math.min(6, (/^#+/.exec(line)?.[0].length ?? 1) + 2); // h3 and below: the page owns h1 and h2
      out.push(createElement(`h${level}`, { key: at }, inline(line.replace(/^#+\s+/, ""))));
      i++;
    } else if (/^\s*([-*+]|\d+[.)])\s/.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items: ReactNode[] = [];
      for (; i < lines.length && /^\s*([-*+]|\d+[.)])\s/.test(next()); i++) {
        items.push(<li key={`i${i}`}>{inline(next().replace(/^\s*([-*+]|\d+[.)])\s+/, ""))}</li>);
      }
      out.push(createElement(ordered ? "ol" : "ul", { key: at }, items));
    } else if (line.trimStart().startsWith("|")) {
      const rows: string[][] = [];
      for (; i < lines.length && next().trimStart().startsWith("|"); i++) {
        if (!/^\s*\|?[\s:|-]+\|?\s*$/.test(next())) rows.push(cells(next()));
      }
      const [head, ...body] = rows;
      out.push(
        <table key={at}>
          <thead>
            <tr>
              {(head ?? []).map((c, n) => (
                <th key={`h${n}:${c}`}>{inline(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((r, n) => (
              <tr key={`r${n}:${r.join("|")}`}>
                {r.map((c, m) => (
                  <td key={`c${m}:${c}`}>{inline(c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
    } else {
      const para: string[] = [];
      for (
        ;
        i < lines.length &&
        next().trim() !== "" &&
        !/^(#{1,6}\s|```|\s*([-*+]|\d+[.)])\s|\s*\|)/.test(next());
        i++
      )
        para.push(next());
      out.push(<p key={at}>{inline(para.join(" "))}</p>);
    }
  }
  return <>{out}</>;
}
