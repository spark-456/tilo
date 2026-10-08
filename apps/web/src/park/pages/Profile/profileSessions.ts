// FR-SET-04: the signed-in sessions list as a pure model. Ids are opaque. Nothing here gains entries, and
// anything it cannot place (an unknown id) changes nothing, so a wrong id never signs everyone out.
// Stand-in list only until the API has a sessions list and revoke (needs contract change: BQ-SET-1).
import type { ProfileSession } from "../../api/types";

/** Remove one session. The current session and unknown ids are left alone. */
export function signOutOne(sessions: readonly ProfileSession[], id: string): ProfileSession[] {
  const hit = sessions.find((s) => s.id === id);
  if (!hit || hit.current) return [...sessions];
  return sessions.filter((s) => s.id !== id);
}

/** Keep only the session named by `currentId`; if it is not in the list, remove nothing. */
export function signOutOthers(
  sessions: readonly ProfileSession[],
  currentId: string,
): ProfileSession[] {
  if (!sessions.some((s) => s.id === currentId)) return [...sessions];
  return sessions.filter((s) => s.id === currentId);
}
