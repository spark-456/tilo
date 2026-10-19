import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { expect, it, vi } from "vitest";
vi.mock("../auth/session", () => ({
  session: {
    getState: () => ({
      status: "google",
      displayName: "Web Founder",
      email: "founder@example.test",
    }),
  },
}));
// This test starts the real FastAPI app through `uv run --no-sync python`. It needs the Python stack to be
// importable. Where it is not (the Cloud Build web step is a Node image whose .venv points at a missing
// interpreter), it is skipped with the reason printed, and runs wherever the venv exists.
// The probe NEVER runs uv: `uv run` on a venv whose interpreter link is dangling removes and recreates that venv
// empty, and the gate's later Python steps share the same /workspace/.venv. It only spawns the venv's own
// interpreter, and only if that file exists (existsSync follows links, so a dangling one counts as missing).
const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));
const probe = (() => {
  const venv = process.env.UV_PROJECT_ENVIRONMENT || join(ROOT, ".venv");
  const python = [join(venv, "bin", "python"), join(venv, "Scripts", "python.exe")].find((p) =>
    existsSync(p),
  );
  if (!python) return "the project venv has no working interpreter";
  try {
    const out = spawnSync(python, ["-c", "import pytest, fastapi"], {
      cwd: ROOT,
      timeout: 30_000,
      encoding: "utf8",
    });
    if (out.status === 0) return null;
    return out.error ? String(out.error.message) : "pytest and fastapi are not importable";
  } catch (e) {
    return String(e);
  }
})();
if (probe)
  console.info(
    `LIVE-PEOPLE integration test skipped: the Python stack is not available (${probe}).`,
  );
it.skipIf(probe !== null)(
  "LIVE-PEOPLE FR-TEAM-01 actual FastAPI fake-store founding through the web client",
  async () => {
    const proc = spawn(
      "uv",
      ["run", "--no-sync", "python", "services/api/tests/_live_people_web_transport.py"],
      {
        cwd: ROOT,
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
    const lines = createInterface({ input: proc.stdout })[Symbol.asyncIterator]();
    let stderr = "";
    proc.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    const next = async () => {
      let line = await lines.next();
      while (
        !line.done &&
        !("status" in JSON.parse(line.value)) &&
        !("ready" in JSON.parse(line.value))
      )
        line = await lines.next();
      if (line.done) throw new Error(`Fake API exited: ${stderr}`);
      return JSON.parse(line.value) as { ready?: boolean; status: number; body: string };
    };
    try {
      expect((await next()).ready).toBe(true);
      const calls: string[] = [];
      const fetchApi = async (url: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(url)).pathname;
        calls.push(`${init?.method ?? "GET"} ${path}`);
        proc.stdin.write(
          `${JSON.stringify({ path, method: init?.method ?? "GET", body: init?.body })}\n`,
        );
        const answer = await next();
        return new Response(answer.body, { status: answer.status });
      };
      // Both protected reads really return 404 before there is a person.
      expect((await fetchApi("https://offline.test/v1/people")).status).toBe(404);
      expect((await fetchApi("https://offline.test/v1/plate")).status).toBe(404);
      const { createLiveApi } = await import("../park/api/liveApi");
      const api = createLiveApi({ baseUrl: "https://offline.test", fetch: fetchApi });
      const team = await api.getTeam();
      expect(team.data.setupRequired).toBeUndefined();
      expect(team.data.people).toMatchObject([
        { id: "u_web_founder", name: "Web Founder", role: "Owner", you: true },
      ]);
      const agenda = await api.getAgenda();
      expect(agenda.data).toMatchObject({ plate: { rows: [], parked: [] } });
      expect("setupRequired" in agenda.data && agenda.data.setupRequired).toBeFalsy();
      expect(calls).toEqual([
        "GET /v1/people",
        "GET /v1/plate",
        "GET /v1/people",
        "POST /v1/people/first",
        "GET /v1/people",
        "GET /v1/plate",
      ]);
    } finally {
      proc.stdin.end();
      proc.kill();
    }
  },
  60000,
);
