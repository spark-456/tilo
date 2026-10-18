// TW-3: Connector islands with real logos (Gmail, Google Drive, Google Calendar only).
// 32 px logo tile placed at the island location, with dashed line to the step building.
import type { Event, Layout } from "@tilo/contracts";
import { BrandIcon } from "../../park/pages/Connectors/BrandIcon";
import { registerProbe } from "../../world/spotlight";

export function isSupportedConnector(idOrName: string): boolean {
  const norm = idOrName.toLowerCase().replace(/[^a-z0-9]/g, "");
  return (
    norm.includes("gmail") ||
    norm.includes("drive") ||
    norm.includes("calendar") ||
    norm.includes("gcal")
  );
}

export function connectorBrand(idOrName: string): { brand: string; mono: string } | null {
  const norm = idOrName.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (norm.includes("gmail")) return { brand: "gmail", mono: "M" };
  if (norm.includes("drive")) return { brand: "google_drive", mono: "D" };
  if (norm.includes("calendar") || norm.includes("gcal")) {
    return { brand: "google_calendar", mono: "C" };
  }
  return null;
}

export function ConnectorLayer({
  worldId,
  layout,
  events,
}: {
  worldId: string;
  layout: Layout | null;
  events: readonly Event[];
}) {
  if (!layout) return null;
  const probe = registerProbe.get(worldId);
  const islands = layout.semantic?.islands ?? [];

  return (
    <>
      {islands
        .filter((i) => isSupportedConnector(i.id) || isSupportedConnector(i.name))
        .map((island) => {
          const brandMeta = connectorBrand(island.id) ?? connectorBrand(island.name);
          if (!brandMeta) return null;
          const pos = probe?.locate(island.id);
          if (!pos) return null;

          const bridge = layout.geometry?.bridges?.find((b) => b.island === island.id);
          const stepBuildingId = bridge?.from;
          const buildingEvents = stepBuildingId
            ? events.filter((e) => e.target === stepBuildingId)
            : [];
          const lastEvent = buildingEvents[buildingEvents.length - 1];
          const isActive =
            lastEvent?.type === "building.constructing" || lastEvent?.type === "approval.requested";

          return (
            <div
              key={island.id}
              className="tw-island-logo"
              data-testid={`island-logo-${island.id}`}
              style={{
                left: pos.x,
                top: pos.y,
              }}
            >
              <span
                className={`tw-island-logo__tile${isActive ? " tw-island-logo__tile--active" : ""}`}
                role="img"
                aria-label={`${island.name} logo slot`}
              >
                <BrandIcon id={brandMeta.brand} mono={brandMeta.mono} />
              </span>
            </div>
          );
        })}
      {islands
        .filter((i) => !isSupportedConnector(i.id) && !isSupportedConnector(i.name))
        .filter((i) => {
          const norm = `${i.id} ${i.name}`.toLowerCase();
          return !norm.includes("canva");
        })
        .map((island) => {
          const pos = probe?.locate(island.id);
          if (!pos) return null;
          return (
            <div
              key={island.id}
              className="tw-island-logo tw-island-logo--later"
              data-testid={`island-later-${island.id}`}
              style={{
                left: pos.x,
                top: pos.y,
              }}
            >
              <span className="tw-island-later__line">Coming later</span>
            </div>
          );
        })}
    </>
  );
}
