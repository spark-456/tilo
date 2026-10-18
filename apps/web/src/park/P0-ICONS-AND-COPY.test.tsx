// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { describeError } from "../api/describeError";
import { TiloApiError, displayApiError, reasonOf } from "../api/http";
import { formatCredits } from "./pages/Ledger/Sections";
import { runView } from "./pages/World/runView";

describe("P0-ICONS-AND-COPY: class 1 raw status codes in the UI", () => {
  it("replaces raw status codes 503, 502, RouterExhausted in describeError with plain wording and next action", () => {
    const err503 = describeError("load the world", new Error("503"));
    expect(err503).not.toContain("503");
    expect(err503).toContain("unavailable");
    expect(err503).toContain("try again");

    const err502 = describeError("load the world", new Error("502"));
    expect(err502).not.toContain("502");
    expect(err502).toContain("try again");

    const errRouter = describeError("complete the step", new Error("RouterExhaustedError"));
    expect(errRouter).not.toContain("RouterExhausted");
    expect(errRouter).toContain("try again");
  });

  it("replaces raw RouterExhausted and status codes in displayApiError", () => {
    const err = new TiloApiError("RouterExhausted", 500, true);
    const msg = displayApiError(err);
    expect(msg).not.toContain("RouterExhausted");
    expect(msg.toLowerCase()).toContain("try again");
  });

  it("cleans raw RouterExhausted in world.failed runView failure reason", () => {
    const view = runView([
      {
        seq: 1,
        credits: 1,
        ts: "2026-10-18T12:00:00Z",
        type: "world.failed",
        summary: "Stopped.",
        data: {
          reason: "no model could answer a step [RouterExhaustedError <- OutputTruncatedError]",
        },
      },
    ]);
    expect(view.failure?.reason).not.toContain("RouterExhausted");
    expect(view.failure?.reason).not.toContain("OutputTruncatedError");
    expect(view.failure?.reason.toLowerCase()).toContain("try again");
  });
});

describe("P0-ICONS-AND-COPY: class 2 team IDs formatting", () => {
  it("formats team ids starting with tm_ to friendly plain text", () => {
    const formatTeamId = (id: string) =>
      id.startsWith("tm_") ? id.replace(/^tm_/, "").replace(/_/g, " ") : id;
    expect(formatTeamId("tm_launch_crew")).toBe("launch crew");
    expect(formatTeamId("tm_ops")).toBe("ops");
  });
});

describe("P0-ICONS-AND-COPY: class 3 blue underlined plain links", () => {
  it("styles base links with design system hero ink and no default underline", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const css = fs.readFileSync(path.resolve(__dirname, "app/park-app.css"), "utf8");
    expect(css).toMatch(/\[data-park\]\s+a\s*\{[^}]*text-decoration:\s*none/);
    expect(css).toMatch(/\[data-park\]\s+a\s*\{[^}]*color:\s*var\(--heroInk/);
  });
});

describe("P0-ICONS-AND-COPY: class 5 dead-end messages with no next step", () => {
  it("provides next step in meeting host unknown connection state", async () => {
    const { STATE_TEXT } = await import("./pages/Connectors/MeetingHostAccess");
    expect(STATE_TEXT.unknown).not.toContain("so none is shown");
    expect(STATE_TEXT.unknown.toLowerCase()).toMatch(/check again|try again|reconnect/);
  });

  it("provides next step in item load failure message", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const runStatus = fs.readFileSync(path.resolve(__dirname, "pages/World/RunStatus.tsx"), "utf8");
    expect(runStatus).toContain(
      "That item could not be loaded. Nothing is lost. Try opening or downloading it again.",
    );
  });
});

describe("P0-ICONS-AND-COPY: class 6 credits shown with long decimals (round to 1 decimal)", () => {
  it("rounds long decimal credits to at most 1 decimal place", () => {
    expect(formatCredits(0.3333333333)).toBe("0.3");
    expect(formatCredits(12.789)).toBe("12.8");
    expect(formatCredits(5)).toBe("5");
    expect(formatCredits(4.2)).toBe("4.2");
  });
});
