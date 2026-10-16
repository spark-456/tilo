import { useEffect, useMemo, useState } from "react";
import { API_URL, appCheckToken, authToken } from "../../../api/ClientProvider";
import { HttpClient } from "../../../api/http";
import type { World } from "../../api/types";
import { peopleListsApi, type PeopleList } from "../../api/live/peopleLists";

type Pins = PeopleList | "loading" | "failed" | "unavailable";

type PinboardReader = ReturnType<typeof peopleListsApi>["getPinboards"];

export function TeamResources({
  worlds,
  readPinboards,
}: { worlds: World[]; readPinboards?: PinboardReader }) {
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
        {shared.length ? (
          <ul>
            {shared.map((world) => (
              <li key={world.id}>{world.name}</li>
            ))}
          </ul>
        ) : (
          <p>No worlds shared with your team yet.</p>
        )}
      </section>
      <section className="park-team-card" aria-label="Team pins">
        <h2 className="park-team-h2">Team pins</h2>
        {pins === "loading" ? (
          <p>Loading team pins…</p>
        ) : pins === "failed" ? (
          <p>Team pins are unavailable right now.</p>
        ) : pins === "unavailable" ? (
          <p>Team pins are not connected on this install.</p>
        ) : teamPins.length ? (
          <ul>
            {teamPins.map((pin) => (
              <li key={pin.id}>{pin.title}</li>
            ))}
          </ul>
        ) : (
          <p>No team pins yet.</p>
        )}
      </section>
    </div>
  );
}
