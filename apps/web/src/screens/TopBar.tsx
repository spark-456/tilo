// The shared app top bar (Bundle C, #227): the logo, the current place and, on the right, what the
// client really knows about the run. Every artboard has this bar (Tilo Home v2, Worlds, World
// Player); the primary nav stays in the rail and the tabs. Real data only: the client has no
// signed-in user, plan or avatar, so none is drawn (HR-1: the Needs-you count is the queue S-06
// lists, from the recorded events).
import { useClient } from "../api/ClientProvider";
import { deriveQueue } from "../needs-you/queue";
import { matchFlowRoute, usePathname } from "../router";
import { useRunLog } from "../world/runLog";
import { useAddressedWorld, withWorld } from "../world/worldContext";
import { AppLink } from "./AppLink";
import { useCountedWorld } from "./PrimaryNav";
import { field } from "./kit";
import { screenMeta } from "./meta";
import { matchScreen } from "./routes";

/** Short place names for screens whose PRD name is a sentence. */
const SHORT: Readonly<Record<string, string>> = {
  "S-06": "Needs you",
  "S-07": "Gate",
  "S-08": "Connection consent",
  "S-14": "Worlds",
  "S-13": "Library",
  "S-23": "How we estimate",
};
/** Screens that belong to one world: the place is that world's title, then the lens. */
const WORLD_LENS: Readonly<Record<string, string>> = {
  "S-05": "Inspect",
  "S-10": "Story",
  "S-11": "Trace",
  "S-12": "Delivery",
};

interface Place {
  readonly name: string;
  /** The lens or step, after the name. */
  readonly sub: string | null;
  /** The world whose title is the name, once its run has recorded one. */
  readonly world: string | null;
}

/** `fixture`: a `?fixture=` replay draws the stage at any address, so "/" is then the world. */
export function placeOf(path: string, fixture = false): Place {
  const matched = matchScreen(path);
  if (matched) {
    if (matched.id === "not-found") return { name: "Not found", sub: null, world: null };
    const lens = WORLD_LENS[matched.id];
    if (lens) return { name: "World", sub: lens, world: matched.params[0] ?? null };
    return {
      name: SHORT[matched.id] ?? screenMeta(matched.id)?.name ?? "Tilo",
      sub: null,
      world: null,
    };
  }
  const flow = matchFlowRoute(path);
  if (flow.screen === "World") return { name: "World", sub: null, world: flow.worldId };
  return fixture
    ? { name: "World", sub: null, world: null }
    : { name: "Home", sub: null, world: null };
}

/** The world's recorded title (its first event carries it), else null. */
function worldTitle(events: readonly { data: unknown }[]): string | null {
  const first = events[0] as Parameters<typeof field>[0] | undefined;
  const title = first ? field(first, "title") : undefined;
  return typeof title === "string" && title.trim() !== "" ? title : null;
}

function Logo() {
  return (
    <AppLink to="/" className="topbar-logo" aria-label="Tilo home">
      <span className="topbar-mark" aria-hidden="true">
        <span className="topbar-face">
          <span className="topbar-eye" />
          <span className="topbar-eye" />
        </span>
      </span>
      <span className="topbar-word" aria-hidden="true">
        tilo
      </span>
    </AppLink>
  );
}

/** The "N decisions waiting" chip. On the queue's own page it is text, not a link to itself. */
export function Waiting({ count, here, to }: { count: number; here: boolean; to: string }) {
  const inner = (
    <>
      <span className="topbar-waiting-count">{count}</span>
      <span className="topbar-waiting-long">
        {count === 1 ? "decision waiting" : "decisions waiting"}
      </span>
      <span className="topbar-waiting-short">waiting</span>
    </>
  );
  return here ? (
    <span className="topbar-waiting" data-testid="top-bar-waiting" aria-current="page">
      {inner}
    </span>
  ) : (
    <AppLink to={to} className="topbar-waiting" data-testid="top-bar-waiting">
      {inner}
    </AppLink>
  );
}

export function TopBar({ fixture }: { fixture: boolean }) {
  const path = usePathname();
  const client = useClient();
  const place = placeOf(path, fixture);
  const inWorld = useAddressedWorld();
  const counted = useCountedWorld();
  // One subscription to the run: the title and the count read the same events.
  const events = useRunLog(client, counted);
  const title = place.world !== null && place.world === counted ? worldTitle(events) : null;
  const waiting = deriveQueue(events).length;
  const name = title ?? place.name;
  const onQueue = matchScreen(path)?.id === "S-06";
  const queueTo = inWorld ? withWorld("/needs-you", inWorld) : "/needs-you";
  return (
    <header className="topbar" data-testid="top-bar">
      <Logo />
      {/* One text box: the lens or step is the name's ::before (data-sub), so a title arriving
          with the run's first event widens the box without moving a second one (CLS). */}
      <p
        className="topbar-place"
        data-testid="top-bar-place"
        data-sub={place.sub ?? ""}
        {...(place.sub ? { "data-has-sub": "" } : {})}
      >
        {name}
      </p>
      {waiting > 0 && <Waiting count={waiting} here={onQueue} to={queueTo} />}
    </header>
  );
}
