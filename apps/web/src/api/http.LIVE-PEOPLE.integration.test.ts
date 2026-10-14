import { spawn } from "node:child_process";
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
it("LIVE-PEOPLE FR-TEAM-01 actual FastAPI fake-store founding through the web client", async () => {
  const proc = spawn(
    "uv",
    ["run", "--no-sync", "python", "services/api/tests/_live_people_web_transport.py"],
    {
      cwd: fileURLToPath(new URL("../../../../", import.meta.url)),
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
}, 60000);
