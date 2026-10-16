import {
  type SimpleIcon,
  siGithub,
  siGmail,
  siGooglecalendar,
  siGoogledocs,
  siGoogledrive,
  siGooglesheets,
  siGoogleslides,
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
  google_docs: siGoogledocs,
  google_sheets: siGooglesheets,
  google_slides: siGoogleslides,
  github: siGithub,
  hubspot: siHubspot,
  jira: siJira,
  notion: siNotion,
  stripe: siStripe,
  xero: siXero,
};
const DARK_MARKS = new Set(["000000", "181717"]);

// Files in public/park/brands are fetched only when a visible connector needs them.
const COLOR_LOGOS: Record<string, string> = {
  gmail: "google-gmail",
  gcal: "google-calendar",
  google_calendar: "google-calendar",
  gdrive: "google-drive",
  google_drive: "google-drive",
  meeting_host: "google-meet",
  microsoft365: "microsoft",
  slack: "slack",
  notion: "notion",
  lovable: "lovable",
  github: "github",
  hubspot: "hubspot",
  jira: "jira",
  stripe: "stripe",
  xero: "xero",
};

export const logoOf = (id: string): SimpleIcon | null => LOGOS[id] ?? null;
export const colorLogoOf = (id: string): string | null =>
  COLOR_LOGOS[id] ? `/park/brands/${COLOR_LOGOS[id]}.svg` : null;

/** The name beside the mark supplies its accessible label; missing brands keep their existing monogram. */
export function BrandIcon({ id, mono }: { id: string; mono: string }) {
  const color = colorLogoOf(id);
  const brand = logoOf(id);
  return color ? (
    <span className="park-connectors-brand" aria-hidden="true">
      <img src={color} alt="" width="25" height="25" loading="lazy" decoding="async" />
    </span>
  ) : brand ? (
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
