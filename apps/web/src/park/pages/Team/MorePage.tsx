import type { AppCtx, PageId } from "../../app/AppCtx";
import { Button, PageSheet } from "../../components";
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
        <nav aria-label="More pages">
          {(
            [
              ["Library", "/library"],
              ["Autonomy", "/autonomy"],
              ["Channels", "/channels"],
              ["Settings", "/settings"],
              ["How we estimate", "/estimate"],
              ["Pilot", "/pilot"],
            ] as const
          ).map(([label, path]) => (
            <a
              key={path}
              href={`${path}${app.params.world ? `?world=${encodeURIComponent(app.params.world)}` : ""}`}
            >
              {label}
            </a>
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
