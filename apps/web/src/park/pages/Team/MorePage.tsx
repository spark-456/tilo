import type { AppCtx, PageId } from "../../app/AppCtx";
import { Button, PageSheet } from "../../components";
import { AppLink } from "../../shared/AppLink";
import "./More.css";
export function MorePage({ app }: { app: AppCtx }) {
  const links: [string, PageId, string?][] = [
    ["Email Autopilot", "team", "mail"],
    ["Team Lead console", "team", "console"],
    ["Connectors", "connectors"],
    ["Profile and settings", "profile"],

    ["Worlds", "worlds"],
    ["Agenda", "agenda"],
    ["Skills", "skills"],
    ["Ledger", "ledger"],
  ];
  return (
    <div data-testid="park-page-more">
      <PageSheet>
        <h1>More</h1>
        <nav aria-label="More pages" className="park-more-nav">
          {(
            [
              ["Library", "/library"],
              ["Autonomy", "/settings?section=autonomy"],
              ["Channels", "/settings?section=channels"],
              ["Settings", "/settings"],
              ["How we estimate", "/settings?section=estimate"],
              ["Pilot", "/settings?section=pilot"],
            ] as const
          ).map(([label, path]) => (
            <AppLink
              key={path}
              className="park-btn park-btn--secondary park-btn--md"
              to={`${path}${app.params.world ? `${path.includes("?") ? "&" : "?"}world=${encodeURIComponent(app.params.world)}` : ""}`}
            >
              {label}
            </AppLink>
          ))}
          {links.map(([label, page, focus]) => (
            <Button
              variant="secondary"
              key={label}
              onClick={() =>
                app.go(page, {
                  ...(focus ? { focus } : {}),
                  ...(app.params.world ? { world: app.params.world } : {}),
                })
              }
            >
              {label}
            </Button>
          ))}
        </nav>
      </PageSheet>
    </div>
  );
}
