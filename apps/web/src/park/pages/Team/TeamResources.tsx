import { useEffect, useMemo, useState } from "react";
import { API_URL, appCheckToken, authToken } from "../../../api/ClientProvider";
import { HttpClient } from "../../../api/http";
import { EmptyState, ErrorState, LoadingState } from "../../../design/tilo-t";
import type { World } from "../../api/types";
import { peopleListsApi, type PeopleList } from "../../api/live/peopleLists";

type Pins = PeopleList | "loading" | "failed" | "unavailable";

type PinboardReader = ReturnType<typeof peopleListsApi>["getPinboards"];

export function TeamResources({
  worlds,
  worldsState,
  readPinboards,
}: {
  worlds: World[];
  worldsState: "loading" | "ready" | "failed";
  readPinboards?: PinboardReader;
}) {
  const http = useMemo(
    () => (API_URL?.trim() ? new HttpClient({ baseUrl: API_URL, appCheckToken, authToken }) : null),
    [],
  );
  const client = useMemo(() => (http ? peopleListsApi(http) : null), [http]);
  const read = readPinboards ?? client?.getPinboards;
  const [pins, setPins] = useState<Pins>(read ? "loading" : "unavailable");
  useEffect(() => {
    let active = true;
    if (read) {
      void read()
        .then((result) => {
          if (active) setPins(result.data);
        })
        .catch(() => {
          if (active) setPins("failed");
        });
    }
    return () => { active = false; };
  }, [read]);
  const shared = worlds.filter((world) => world.access === "team");
  const teamPins =
    pins && typeof pins === "object"
      ? pins.rows.filter((pin) => pin.scope?.startsWith("Team "))
      : [];
  return (
    <div className="park-team-resources">
      <section className="park-team-card" aria-label="Shared worlds">
        <h2 className="park-team-h2">Shared worlds</h2>
        {worldsState === "loading" ? (
          <LoadingState layout="list" caption="Loading shared worlds" />
        ) : worldsState === "failed" ? (
          <ErrorState title="Shared worlds aren’t available" body="Try again later." />
        ) : shared.length ? (
          <ul>
            {shared.map((world) => (
              <li key={world.id}>{world.name}</li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No shared worlds yet" body="Worlds shared with your team will show up here." />
        )}
      </section>
      <section className="park-team-card" aria-label="Team pins">
        <h2 className="park-team-h2">Team pins</h2>
        {pins === "loading" ? (
          <LoadingState layout="list" caption="Loading team pins" />
        ) : pins === "failed" ? (
          <ErrorState title="Team pins are unavailable" body="Try again later." />
        ) : pins === "unavailable" ? (
          <EmptyState title="Team pins aren’t connected" body="Pinboards are not set up on this install." />
        ) : teamPins.length ? (
          <ul>
            {teamPins.map((pin) => (
              <li key={pin.id}>{pin.title}</li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No team pins yet" body="Pins shared with your team will show up here." />
        )}
      </section>
    </div>
  );
}
