// FR-SKL-01 S3 browser rig: the real Skills page with an injected live Api.
// This Vite-only entry never uses the local auth session or production API.
import { createRoot } from "react-dom/client";
import type { Api } from "../../src/park/api";
import { createFixtureApi } from "../../src/park/api/fixtureApi";
import { learn, user } from "../../src/park/api/fixtures";
import { ParkProvider, useApp } from "../../src/park/app/context";
import { SkillsPage } from "../../src/park/pages/Skills/SkillsPage";

const live = <T,>(data: T) => Promise.resolve({ data, source: "live" as const });
const api: Api = {
  ...createFixtureApi(),
  getSkills: () => live([]),
  getLearn: () => live(learn),
  getUser: () => live(user),
  captureFile: (file, onStored, method) => {
    if (file.type !== "video/webm" || method !== "record" || file.size === 0)
      return Promise.reject(new Error("Expected a nonempty screen recording"));
    document.body.dataset.captures = String(Number(document.body.dataset.captures) + 1);
    onStored?.();
    return live({ id: "browser-recording", steps: ["Open the page and review the request."] });
  },
};

function Harness() {
  return <SkillsPage app={useApp()} />;
}

const root = document.getElementById("root");
if (!root) throw new Error("Skills browser test root is missing");
createRoot(root).render(
  <ParkProvider api={api}>
    <Harness />
  </ParkProvider>,
);
