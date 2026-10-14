import type { RunEvent } from "./useRunEvents";

interface District {
  id: string;
  name: string;
  buildings: Map<string, string>;
}
interface Agent {
  id: string;
  district: string | null;
  role: string;
  state: string;
}

function word(event: RunEvent, key: string): string | undefined {
  const value = event.data && typeof event.data === "object" ? Reflect.get(event.data, key) : null;
  return typeof value === "string" ? value : undefined;
}

/** Park's overview is a diagram of recorded entities, not a guessed stage layout.
 * No timers, sample geometry, or motion: every new entity/state requires its own event. */
export function recordedWorld(events: readonly RunEvent[]) {
  const districts = new Map<string, District>();
  const agents = new Map<string, Agent>();
  for (const event of events) {
    if (!event.target) continue;
    if (event.type === "district.created") {
      if (!districts.has(event.target)) {
        districts.set(event.target, {
          id: event.target,
          name: word(event, "name") ?? event.target,
          buildings: new Map(),
        });
      }
    }
    const district = event.district ? districts.get(event.district) : undefined;
    if (event.type === "building.planned" && district)
      district.buildings.set(event.target, "planned");
    if (event.type === "building.completed" && district?.buildings.has(event.target)) {
      district.buildings.set(event.target, "completed");
    }
    if (event.type === "agent.spawned") {
      agents.set(event.target, {
        id: event.target,
        district: event.district ?? null,
        role: word(event, "role") ?? event.target,
        state: "spawned",
      });
    }
    const agent = agents.get(event.actor ?? "") ?? agents.get(event.target);
    if (agent && event.type.startsWith("agent.") && event.type !== "agent.spawned") {
      agent.state = event.type.slice("agent.".length);
      if (event.district) agent.district = event.district;
    }
  }
  return { districts: [...districts.values()], agents: [...agents.values()] };
}

export function RecordedWorldArt({ events }: { events: readonly RunEvent[] }) {
  const { districts, agents } = recordedWorld(events);
  if (districts.length === 0 && agents.length === 0) {
    return <output>Waiting for recorded districts and agents…</output>;
  }
  return (
    <div
      data-recorded-world=""
      aria-label="Recorded world map"
      style={{ width: "100%", maxHeight: "100%", overflow: "auto" }}
    >
      {districts.map((district) => {
        const team = agents.filter((agent) => agent.district === district.id);
        const height = 80 + district.buildings.size * 32 + team.length * 32;
        return (
          <svg
            key={district.id}
            data-recorded-district={district.id}
            role="img"
            aria-label={`District ${district.name}`}
            viewBox={`0 0 340 ${height}`}
            style={{ width: "100%", maxWidth: 340, display: "inline-block" }}
          >
            <title>{`District ${district.name}`}</title>
            <rect
              x="4"
              y="4"
              width="332"
              height={height - 8}
              rx="16"
              fill="var(--surface, #fff)"
              stroke="currentColor"
            />
            <text x="20" y="34" fill="currentColor">
              {district.name}
            </text>
            {[...district.buildings].map(([id, state], i) => (
              <g key={id} data-recorded-building={id} transform={`translate(20 ${58 + i * 32})`}>
                <rect width="18" height="18" rx="3" fill="none" stroke="currentColor" />
                <text x="28" y="14" fill="currentColor">{`${id} · ${state}`}</text>
              </g>
            ))}
            {team.map((agent, i) => (
              <g
                key={agent.id}
                data-recorded-agent={agent.id}
                transform={`translate(20 ${58 + district.buildings.size * 32 + i * 32})`}
              >
                <circle cx="9" cy="9" r="8" fill="none" stroke="currentColor" />
                <text x="28" y="14" fill="currentColor">{`${agent.role} · ${agent.state}`}</text>
              </g>
            ))}
          </svg>
        );
      })}
      {agents
        .filter((agent) => !districts.some((district) => district.id === agent.district))
        .map((agent) => (
          <svg
            key={agent.id}
            data-recorded-agent={agent.id}
            role="img"
            aria-label={`Agent ${agent.role}`}
            viewBox="0 0 340 36"
            style={{ width: "100%", maxWidth: 340 }}
          >
            <title>{`Agent ${agent.role}`}</title>
            <circle cx="12" cy="16" r="8" fill="none" stroke="currentColor" />
            <text x="30" y="21" fill="currentColor">{`${agent.role} · ${agent.state}`}</text>
          </svg>
        ))}
    </div>
  );
}
