// Hand-written from design_handoff_tilo_web_app/design/Tilo App Team.dc.html (const LIM, line 122;
// the backup wait, line 133), not generated: these values are not in tilo-app.js, so
// scripts/park-fixtures.mjs does not write this file. Scenario content lives in api/fixtures only.
import type { TeamPolicy } from "../types";

export const teamPolicy: TeamPolicy = {
  roleLimits: { Owner: "No limit", Approver: "£1,000", Member: "£250", Viewer: "—" },
  backupWait: "About 20 min",
};
