// The one switch for the city's ambient motion (cars and walkers; BQ-WEB-3, ADR-0003a 5). On by default;
// set VITE_PARK_AMBIENT_MOTION to 0, false or off to draw the city frozen. This is the only file that reads it.
const raw = import.meta.env.VITE_PARK_AMBIENT_MOTION as string | undefined;

export const AMBIENT_ON: boolean = raw === undefined || !/^(?:0|false|off)$/i.test(raw.trim());
