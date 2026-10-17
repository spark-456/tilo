import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { RunPlan } from "../../api/oneStep";
import { RunCard } from "./RunCard";

const plan: RunPlan = {
  taskId: "t_1",
  goal: "Summarise this",
  lines: [],
  approachId: "a_1",
  approachLabel: "Balanced",
  credits: { min: 60, max: 60 },
  cap: 60,
  usd: 3,
  time: "2–5 min",
  makeChoices: [],
  skill: {
    id: "exec_summary",
    kind: "library",
    scope: "library",
    name: "Executive summary",
    version: "1.0.0",
    score: 0.9,
    source: "matched",
  },
};

describe("FR-SKL-04 served skill on the start plan", () => {
  it("FR_SKL_04_ROUTE_names_the_skill_only_when_the_approaches_reply_has_one", () => {
    const render = (value: RunPlan) =>
      renderToStaticMarkup(
        <RunCard
          plan={value}
          busy={false}
          error={null}
          onStart={() => {}}
          onCancel={() => {}}
          onEdit={() => {}}
        />,
      );
    expect(render(plan)).toContain("Uses skill: Executive summary");
    expect(render({ ...plan, skill: null })).not.toContain("Uses skill:");
  });
});
