// FR-SET-05: beta metadata and a server-filtered directory count, display only.
import { useEffect, useState } from "react";
import { useParkApi } from "../../app/context";

export function BetaPlan() {
  const api = useParkApi();
  const [seats, setSeats] = useState<number | "loading" | "unavailable">("loading");
  useEffect(() => {
    let active = true;
    setSeats("loading");
    api.getTeam().then(
      (result) => {
        if (active)
          setSeats(
            result.source === "live"
              ? new Set(result.data.people.map((p) => p.id)).size
              : "unavailable",
          );
      },
      () => {
        if (active) setSeats("unavailable");
      },
    );
    return () => {
      active = false;
    };
  }, [api]);
  return (
    <div className="park-profile-plan park-profile-unavailable">
      <span className="park-profile-eyebrow">PLAN</span>
      <span className="park-profile-planname">Beta, no billing</span>
      <output className="park-profile-blurb" aria-live="polite">
        {typeof seats === "number"
          ? `${seats} ${seats === 1 ? "seat" : "seats"}`
          : seats === "loading"
            ? "Reading team seats"
            : "Team seats unavailable"}
      </output>
      <p className="park-profile-blurb">Based on team members visible to you</p>
      <p className="park-profile-blurb">No renewal date during beta</p>
    </div>
  );
}
