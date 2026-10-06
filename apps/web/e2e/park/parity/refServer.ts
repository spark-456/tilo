// WEB-PARITY: a tiny static server for the read-only design reference (no dependency). Serves
// `design_handoff_tilo_web_app/design/`; support.js only ever runs in the browser to show the reference.
import { readFile } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

export const DESIGN_DIR = resolve(
  fileURLToPath(new URL(".", import.meta.url)),
  "../../../../../design_handoff_tilo_web_app/design",
);
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};

/** Start the reference server on `port` (0 = any free port). Close it with `server.close()`. */
export async function startRefServer(port: number): Promise<{ server: Server; origin: string }> {
  const server = createServer(async (req, res) => {
    const path = normalize(
      join(DESIGN_DIR, decodeURIComponent((req.url ?? "/").split(/[?#]/)[0] ?? "")),
    );
    if (path !== DESIGN_DIR && !path.startsWith(DESIGN_DIR + sep)) {
      res.writeHead(403).end("forbidden");
      return;
    }
    try {
      const body = await readFile(path);
      res.writeHead(200, { "content-type": TYPES[extname(path)] ?? "application/octet-stream" });
      res.end(body);
    } catch {
      res.writeHead(404).end("not found");
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  return { server, origin: `http://127.0.0.1:${(server.address() as AddressInfo).port}` };
}
