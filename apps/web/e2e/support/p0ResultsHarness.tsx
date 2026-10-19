import { createRoot } from "react-dom/client";
import type { RunEvent } from "../../src/park/pages/World/useRunEvents";
import { ResultTab } from "../../src/worldView/live/ResultTab";
import "../../src/park/tokens/park.css";
import "../../src/park/pages/World/World.css";
import "../../src/worldView/live/live.css";

const recorded = [
  {
    seq: 1,
    type: "artifact.created",
    ts: "2026-10-19T10:00:00.000Z",
    credits: 0,
    summary: "The writer made the decision brief.",
    item: { label: "Decision brief.md" },
    data: { artifact: { artifact_id: "main", version: 1 }, media_type: "text/markdown" },
  },
  {
    seq: 2,
    type: "artifact.delivered",
    ts: "2026-10-19T10:01:00.000Z",
    credits: 0,
    summary: "Decision brief is ready.",
    data: { artifact: { artifact_id: "main", version: 1 }, format: "md" },
  },
  {
    seq: 3,
    type: "artifact.delivered",
    ts: "2026-10-19T10:02:00.000Z",
    credits: 0,
    summary: "Research notes are ready.",
    data: {
      artifact: {
        artifact_id: "notes",
        label: "Supplier comparison and recommendations for the October launch.md",
      },
      format: "md",
    },
  },
] as RunEvent[];

const text =
  "# Decision brief\n\nThe team recommends option B.\n\nMove $\\to$ the next review after approval.\n\n| Option | Cost |\n| --- | --- |\n| A | £12 |\n| B | £9 |";
const host = document.createElement("main");
host.dataset.park = "";
host.dataset.testid = "result-visual-host";
host.dataset.time = new URLSearchParams(location.search).get("theme") === "dark" ? "night" : "day";
host.style.cssText =
  "min-height:100vh;width:100%;background:var(--paper);padding:20px;box-sizing:border-box";
const column = document.createElement("div");
column.style.cssText = "max-width:860px;margin:0 auto;min-width:0";
host.append(column);
document.body.replaceChildren(host);
createRoot(column).render(
  <ResultTab
    worldId="recorded-result"
    events={recorded}
    shared={{
      view: {
        status: "text",
        blob: new Blob([text], { type: "text/markdown" }),
        text,
        kind: "markdown",
        cut: false,
      },
      retry: () => undefined,
    }}
  />,
);
