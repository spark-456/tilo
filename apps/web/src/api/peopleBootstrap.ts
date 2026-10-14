import { session } from "../auth/session";

// W-FOUND-1 / FR-PPL: one intent per API origin for this page's person. Sign-out or
// identity change reloads the page, clearing this map along with the other clients.
// Keep failed promises too: an uncertain write must never be automatically retried.
const attempts = new Map<string, Promise<boolean>>();

export function bootstrapPerson(
  origin: string,
  post: (body: unknown) => Promise<unknown>,
  isRefused: (error: unknown) => boolean,
): Promise<boolean> {
  const existing = attempts.get(origin);
  if (existing) return existing;
  const profile = session.getState();
  if (profile.status !== "google" || !profile.email?.trim()) return Promise.resolve(false);
  const email = profile.email.trim();
  const body = {
    display_name: profile.displayName?.trim() || email.split("@")[0],
    email,
    aliases: [],
    time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    preferred_channel: "web",
  };
  const attempt = Promise.resolve().then(async () => {
    try {
      await post(body);
      return true;
    } catch (error) {
      if (isRefused(error)) return false;
      throw error;
    }
  });
  attempts.set(origin, attempt);
  return attempt;
}
