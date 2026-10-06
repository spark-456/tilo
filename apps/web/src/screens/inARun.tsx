// A guard for the screens that read one run's cards and events from a bare address (/needs-you,
// /needs-you/gate, /library; CP2, #258). The world is the addressed one, else the one this session
// started last. With a live API and neither, there is no run: the screen says "No run yet" instead
// of asking the API about the fixture world (a 404 or 403 on every poll). A world the client does
// not know is "Not found", in fixture mode (`?world=bogus`) and live alike.
import type { ComponentType, ElementType } from "react";
import { useWorldKnown } from "../api/ClientProvider";
import { useRunWorld } from "../world/worldContext";
import { AppLink } from "./AppLink";
import { NotFound } from "./NotFound";
import { Page } from "./kit";
import type { ScreenProps } from "./routes";

export function inARun(
  Screen: ElementType<ScreenProps>,
  page: { testid: string; title: string },
): ComponentType<ScreenProps> {
  return function InARun(props: ScreenProps) {
    const world = useRunWorld();
    const known = useWorldKnown(world);
    if (world === null) {
      return (
        <Page {...page} sub="Nothing has started yet, so there is nothing to show here.">
          <p className="empty-note" data-testid="no-run">
            No run yet. Describe some work and its run shows up here.
          </p>
          <AppLink to="/" className="secondary">
            Back to Start
          </AppLink>
        </Page>
      );
    }
    return known ? <Screen {...props} /> : <NotFound />;
  };
}
