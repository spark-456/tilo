// FR-UX-10: the Park shell's seam to the sign-in layer. `ParkAuth` has the shape CL-REACH plans for
// `useAuth()` (names not final), so the real hook's return value can be passed to <ParkAuthProvider auth=...>
// unchanged. Without a provider there is no auth: the shell keeps its prototype behaviour. Sign-in itself is
// not built here.
import { type ReactNode, createContext, useContext } from "react";

export interface ParkAuthUser {
  displayName: string | null;
  email: string | null;
  isAnonymous: boolean;
}

export interface ParkAuth {
  status: "loading" | "signedOut" | "signedIn";
  user: ParkAuthUser | null;
  signInWithGoogle(): Promise<unknown>;
  signInAnonymously(): Promise<unknown>;
  signOut(): Promise<void>;
}

const Ctx = createContext<ParkAuth | null>(null);

export function ParkAuthProvider({
  auth,
  children,
}: { auth: ParkAuth | null; children: ReactNode }) {
  return <Ctx.Provider value={auth}>{children}</Ctx.Provider>;
}

/** The sign-in layer, or null when the shell runs without one. */
export const useParkAuth = (): ParkAuth | null => useContext(Ctx);

/** Two letters for the avatar: the name's first letters, else the email's first letter, else a question mark. */
export function authInitials(user: ParkAuthUser | null): string {
  const name = user?.displayName?.trim();
  if (name) {
    const parts = name.split(/\s+/);
    const a = parts[0]?.[0] ?? "";
    const b = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
    return (a + b).toUpperCase();
  }
  const mail = user?.email?.trim()[0];
  return mail ? mail.toUpperCase() : "?";
}
