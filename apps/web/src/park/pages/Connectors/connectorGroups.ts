import type { Connector } from "../../api/types";

const CATEGORY: Record<string, string> = {
  gmail: "Email",
  gdrive: "Files",
  google_drive: "Files",
  notion: "Files",
  gcal: "Calendar",
  google_calendar: "Calendar",
  meeting_host: "Meetings",
  lovable: "Build",
  canva: "Build",
  jira: "Build",
  github: "Build",
  slack: "Communication",
  m365: "Productivity",
  microsoft365: "Productivity",
  xero: "Business",
  hubspot: "Business",
  stripe: "Business",
  bamboo: "Business",
  bamboohr: "Business",
  web: "Web",
};

/** Live records have no category field, so derive headings only from their known connector IDs. */
export function groupConnectors<T extends Connector>(connectors: readonly T[]) {
  const groups = new Map<string, T[]>();
  for (const connector of connectors) {
    const heading = CATEGORY[connector.id] ?? (connector.cat || "Other");
    const members = groups.get(heading) ?? [];
    members.push(connector);
    groups.set(heading, members);
  }
  return [...groups].map(([heading, members]) => ({ heading, connectors: members }));
}
