import type { Layout, LayoutBuilding } from "@tilo/contracts";
import { type ReactNode, useEffect, useState } from "react";
import type { Plan, World } from "../api/types";
import type { Plan as EnginePlan } from "../engines/types";
import { cachedCity } from "../shell/cityCache";
import { icon, parkKit } from "../shell/kit";
import "./WorldThumbnail.css";
type Tier = World["tier"];
type Look = readonly [roof: string, facade: string];
type ThumbnailPlan = Plan & EnginePlan;
type ThumbnailBuilding = Plan["districts"][number]["buildings"][number] &
  EnginePlan["districts"][number]["buildings"][number];
export interface WorldThumbnailClient {
  getJson(path: string): Promise<unknown>;
}
const COMMON_LOOK: Readonly<Record<string, Look>> = {
  town_hall: ["dome", "arches"],
  your_desk: ["gable", "windows"],
  library: ["gable", "arches"],
  browser_station: ["flat", "band"],
  workshop: ["gable", "windows"],
  meeting_hall: ["dome", "arches"],
  connector_post: ["flat", "band"],
  memory_vault: ["dome", "windows"],
  treasury: ["dome", "arches"],
  watchtower: ["gable", "windows"],
  delivery_dock: ["flat", "windows"],
  clock_tower: ["dome", "arches"],
  agent_foundry: ["flat", "band"],
  mail_room: ["gable", "windows"],
  expert_office: ["flat", "band"],
};
const DISTRICT_TINT = ["research", "analysis", "delivery", "accounts", "people", "learning"];
const size = (value: number | undefined): number =>
  Math.max(1, Math.min(3, Math.round(value ?? 1)));

function buildingPlan(
  building: LayoutBuilding,
  iconName: string,
  geometry: Layout["geometry"],
): ThumbnailBuilding {
  const placed = geometry?.buildings.find((item) => item.id === building.id);
  const look = COMMON_LOOK[building.common_type ?? ""] ?? ["flat", "windows"];
  return {
    id: building.id,
    name: building.name,
    state: "active",
    gen: {
      name: building.name,
      fp: [size(placed?.footprint.w), size(placed?.footprint.d)],
      fl: Math.max(1, placed?.floors ?? 1),
      roof: look[0],
      fa: look[1],
      i: building.kit?.icon ?? iconName,
    },
  };
}
export function layoutPlan(layout: Layout): ThumbnailPlan {
  let index = 0;
  return {
    districts: layout.semantic.levels.flatMap((level) =>
      level.districts.map((district) => {
        const tintRole = layout.geometry?.districts.find((item) => item.id === district.id)?.tint;
        const tintIndex = Math.max(0, Number(tintRole?.split(".")[1] ?? index + 1) - 1);
        index += 1;
        return {
          id: district.id,
          name: district.name,
          icon: district.icon,
          tint: DISTRICT_TINT[tintIndex % DISTRICT_TINT.length],
          buildings: district.buildings.map((building) =>
            buildingPlan(building, district.icon, layout.geometry),
          ),
        };
      }),
    ),
    agents: [],
  };
}
interface Read {
  value?: Layout | null;
  promise: Promise<Layout | null>;
}
let reads = new WeakMap<WorldThumbnailClient, Map<string, Read>>();
function isLayout(value: unknown): value is Layout {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Layout>;
  return (
    candidate.v === "1.0" &&
    typeof candidate.world_id === "string" &&
    Array.isArray(candidate.semantic?.levels) &&
    Array.isArray(candidate.semantic?.agents)
  );
}
function readLayout(client: WorldThumbnailClient, worldId: string): Read {
  let clientReads = reads.get(client);
  if (!clientReads) {
    clientReads = new Map();
    reads.set(client, clientReads);
  }
  const known = clientReads.get(worldId);
  if (known) return known;
  const read: Read = {
    promise: client
      .getJson(`/v1/worlds/${encodeURIComponent(worldId)}/layout`)
      .then(
        (value) => (isLayout(value) && value.world_id === worldId ? value : null),
        () => null,
      )
      .then((value) => {
        read.value = value;
        return value;
      }),
  };
  clientReads.set(worldId, read);
  return read;
}
function useLayout(client: WorldThumbnailClient | null, worldId: string): Layout | null {
  const cached = client ? reads.get(client)?.get(worldId) : undefined;
  const [layout, setLayout] = useState<Layout | null>(cached?.value ?? null);
  useEffect(() => {
    let live = true;
    if (!client) {
      setLayout(null);
      return () => {
        live = false;
      };
    }
    const read = readLayout(client, worldId);
    if (read.value !== undefined) setLayout(read.value);
    else read.promise.then((value) => live && setLayout(value));
    return () => {
      live = false;
    };
  }, [client, worldId]);
  return layout;
}

const KIND_ICONS: Readonly<Record<string, string>> = {
  City: "grid",
  Town: "clock",
  Village: "bolt",
  Workspace: "grid",
  Routine: "clock",
  "Quick task": "bolt",
};

export function kindIconOf(world: World): string {
  return KIND_ICONS[world.tier] || KIND_ICONS[world.tool] || "bolt";
}

export function initialOf(world: World): string {
  const label = world.name?.trim() || world.short?.trim() || world.tier || "W";
  return (label[0] || "W").toUpperCase();
}

// P0-WORLDS-CARDS: clean soft gradient tile with world's initial and kind icon (no black cubes)
function SoftGradientTile({ world }: { world: World }) {
  const initial = initialOf(world);
  const iconName = kindIconOf(world);
  const tierClass = (world.tier || "Village").toLowerCase();
  return (
    <div
      className={`park-worldthumb__tile park-worldthumb__tile--${tierClass}`}
      data-testid="world-gradient-tile"
    >
      <div className="park-worldthumb__tile-inner">
        <span className="park-worldthumb__initial">{initial}</span>
        <span className="park-worldthumb__kind" aria-hidden="true" title={world.tier}>
          {icon(iconName, 18)}
        </span>
      </div>
    </div>
  );
}

function layoutArt(layout: Layout, night: boolean): ReactNode {
  const plan = layoutPlan(layout);
  return cachedCity(
    plan,
    night,
    (recorded, dark) => parkKit().TP.world(recorded, { night: dark }) as ReactNode,
  );
}
export function WorldThumbnail({
  world,
  client,
  night,
  fallback,
}: {
  world: World;
  client: WorldThumbnailClient | null;
  night: boolean;
  fallback?: ReactNode;
}) {
  const layout = useLayout(client, world.id);
  const content = layout
    ? layoutArt(layout, night)
    : fallback || <SoftGradientTile world={world} />;
  const kind = layout
    ? "layout"
    : fallback
      ? "recorded"
      : `placeholder-${world.tier.toLowerCase()}`;
  return (
    <span className="park-worldthumb" data-world-thumbnail={kind} aria-hidden="true">
      {content}
    </span>
  );
}

export function clearWorldThumbnailCache(): void {
  reads = new WeakMap();
}
