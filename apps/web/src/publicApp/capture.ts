/** A first-party asset runs in the opaque-origin frame; model inline scripts stay blocked by the site CSP. */
export function captureHtml(html: string): string {
  const script = '<script src="/app-capture.js"></script>';
  return /<\/body\s*>/i.test(html)
    ? html.replace(/<\/body\s*>/i, `${script}</body>`)
    : html + script;
}
