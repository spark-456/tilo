// The one switch for the city's ambient motion (cars and walkers; BQ-WEB-3, ADR-0003a 5). On by default:
// unset, empty, 1, true or on keep the motion; any other value (0, false, off, a typo) draws the city frozen.
// This is the only file that reads the PARK_AMBIENT_MOTION flag (the Vite variable VITE_PARK_AMBIENT_MOTION).

/** Pure, so a test can pass any value. */
export function ambientOn(raw: string | undefined): boolean {
  if (raw === undefined) return true;
  return /^(?:|1|true|on)$/i.test(raw.trim());
}

export const AMBIENT_ON: boolean = ambientOn(
  import.meta.env.VITE_PARK_AMBIENT_MOTION as string | undefined,
);
