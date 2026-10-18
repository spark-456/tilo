import type { Layout, LayoutBuilding } from "@tilo/contracts";
import { type ReactNode, useEffect, useState } from "react";
import type { Plan, World } from "../api/types";
import type { Plan as EnginePlan } from "../engines/types";
import { cachedCity } from "../shell/cityCache";
import { parkKit } from "../shell/kit";
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
  icon: string,
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
      i: building.kit?.icon ?? icon,
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
const BLOCKS: Readonly<Record<Tier, ReadonlyArray<readonly [number, number]>>> = {
  Village: [[60, 45]],
  Town: [
    [32, 55],
    [74, 40],
    [116, 58],
  ],
  City: [
    [25, 58],
    [58, 34],
    [91, 58],
    [124, 34],
    [157, 58],
    [190, 34],
  ],
};
function Placeholder({ tier }: { tier: Tier }) {
  return (
    <svg
      className={`park-worldthumb__placeholder park-worldthumb__placeholder--${tier.toLowerCase()}`}
      viewBox="0 0 240 132"
      aria-hidden="true"
      focusable="false"
    >
      <path className="park-worldthumb__ground" d="M18 86 120 28l102 58-102 38Z" />
      {BLOCKS[tier].map(([x, y], index) => (
        <g className="park-worldthumb__block" key={`${x}-${y}`}>
          <path d={`M${x} ${y}l16-9 16 9-16 9Z`} />
          <path d={`M${x} ${y}v22l16 9V${y + 9}Z`} />
          <path d={`M${x + 32} ${y}v22l-16 9V${y + 9}Z`} />
          {index === 0 ? (
            <path className="park-worldthumb__door" d={`M${x + 20} ${y + 18}v9l7-4v-9Z`} />
          ) : null}
        </g>
      ))}
    </svg>
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
  const content = layout ? layoutArt(layout, night) : fallback || <Placeholder tier={world.tier} />;
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
