// WEB-PARITY self-test: the harness itself works (parity project only, `TILO_PARITY=1`).
import { expect, test } from "@playwright/test";
import { decode, diffImages } from "./diff";
import { startRefServer } from "./refServer";

test("WEB_PARITY reference server serves a .dc.html and refuses paths outside design/", async ({
  request,
}) => {
  const { server, origin } = await startRefServer(0);
  try {
    const ok = await request.get(`${origin}/${encodeURIComponent("Tilo App Team.dc.html")}`);
    expect(ok.status()).toBe(200);
    expect(ok.headers()["content-type"]).toContain("text/html");
    expect(await ok.text()).toContain("<x-dc>");
    expect((await request.get(`${origin}/..%2FREADME.md`)).status()).toBe(403);
    expect((await request.get(`${origin}/nope.html`)).status()).toBe(404);
  } finally {
    server.close();
  }
});

test("WEB_PARITY a screenshot pair is produced and an image diffed against itself is 0%", async ({
  page,
}) => {
  const { server, origin } = await startRefServer(0);
  try {
    await page.goto(`${origin}/${encodeURIComponent("Tilo App Team.dc.html")}`);
    const a = decode(await page.screenshot({ fullPage: true }));
    const b = decode(await page.screenshot({ fullPage: true }));
    expect(a.width).toBeGreaterThan(0);
    expect(diffImages(a, a).pct).toBe(0);
    expect(diffImages(a, b).sizeMismatch).toBe(false);
  } finally {
    server.close();
  }
});
