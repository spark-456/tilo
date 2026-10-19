// FR-SPD-08: hand a CSV to the browser as a real file download: a Blob, an object URL, a click on an anchor
// that is removed again, and the URL revoked. A leading byte-order mark makes Excel read the text as UTF-8
// (the Ledger's amounts and words carry "£" and "·").
export function downloadCsv(fileName: string, text: string): void {
  const url = URL.createObjectURL(new Blob(["﻿", text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.hidden = true;
  document.body.appendChild(a);
  try {
    a.click();
  } finally {
    a.remove();
    URL.revokeObjectURL(url);
  }
}
