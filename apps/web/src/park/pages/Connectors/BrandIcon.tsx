import {
  type SimpleIcon,
  siGithub,
  siGmail,
  siGooglecalendar,
  siGoogledrive,
  siHubspot,
  siJira,
  siNotion,
  siStripe,
  siXero,
} from "simple-icons";

const LOGOS: Record<string, SimpleIcon> = {
  gmail: siGmail,
  gcal: siGooglecalendar,
  google_calendar: siGooglecalendar,
  gdrive: siGoogledrive,
  google_drive: siGoogledrive,
  github: siGithub,
  hubspot: siHubspot,
  jira: siJira,
  notion: siNotion,
  stripe: siStripe,
  xero: siXero,
};
const DARK_MARKS = new Set(["000000", "181717"]);

export const logoOf = (id: string): SimpleIcon | null => LOGOS[id] ?? null;

/** The name beside the mark supplies its accessible label; missing brands keep their existing monogram. */
export function BrandIcon({ id, mono }: { id: string; mono: string }) {
  const brand = logoOf(id);
  return brand ? (
    <span className="park-connectors-brand" aria-hidden="true">
      {/* biome-ignore lint/a11y/noSvgWithoutTitle: decorative mark; the adjacent name labels the connector */}
      <svg data-brand-icon={id} viewBox="0 0 24 24" width="25" height="25" focusable="false">
        <path
          d={brand.path}
          fill={DARK_MARKS.has(brand.hex.toLowerCase()) ? "var(--ink)" : `#${brand.hex}`}
        />
      </svg>
      <span hidden>{mono}</span>
    </span>
  ) : (
    <span data-monogram={id} aria-hidden="true">
      {mono}
    </span>
  );
}
