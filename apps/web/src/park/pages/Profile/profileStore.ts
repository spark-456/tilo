// FR-SET-01 fixture store: the saved Profile form, per signed-in user. Nothing is sent to a server (the live
// profile endpoint does not exist yet), so a save is "kept on this device only": localStorage under a key per
// user, plus an in-memory copy that keeps working when storage is blocked or throws (private mode, tests).
export const PROFILE_FIELDS = ["name", "email", "title", "tz", "lang", "hours"] as const;
export type ProfileForm = Record<(typeof PROFILE_FIELDS)[number], string>;

const memory = new Map<string, ProfileForm>();

/** One key per user (the signed-in email, not the editable form field). */
export const profileKey = (userKey: string): string => `tilo.profile.${userKey}`;

function parse(raw: string | null): ProfileForm | null {
  if (!raw) return null;
  try {
    const v: unknown = JSON.parse(raw);
    if (typeof v !== "object" || v === null) return null;
    const out: Partial<ProfileForm> = {};
    for (const f of PROFILE_FIELDS) {
      const s = (v as Record<string, unknown>)[f];
      if (typeof s !== "string") return null;
      out[f] = s;
    }
    return out as ProfileForm;
  } catch {
    return null;
  }
}

export function saveProfile(userKey: string, form: ProfileForm): void {
  const copy = { ...form };
  memory.set(userKey, copy);
  try {
    window.localStorage.setItem(profileKey(userKey), JSON.stringify(copy));
  } catch {
    // storage absent or blocked: the in-memory copy still serves this session
  }
}

export function loadProfile(userKey: string): ProfileForm | null {
  try {
    const stored = parse(window.localStorage.getItem(profileKey(userKey)));
    if (stored) return stored;
  } catch {
    // storage absent or blocked: fall through to memory
  }
  const m = memory.get(userKey);
  return m ? { ...m } : null;
}

/** Forget the in-memory copies (tests; localStorage is cleared by the caller). */
export function clearProfileStore(): void {
  memory.clear();
}
