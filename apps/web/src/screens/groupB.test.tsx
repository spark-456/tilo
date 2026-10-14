// @vitest-environment happy-dom
// AGW-08 group B honesty (HR-1, PRD 9.4): what S-13, S-17, S-18 and S-19 show follows the
// recorded events of the run, whatever the client would answer. Each case renders the screen on a
// run that has recorded only the first events (a prefix of the village stream), so the moments
// between events are tested exactly, not by timing.
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { MailSection as S_17 } from "../park/pages/Team/RunAdmin";
import { ConsoleSection as S_18 } from "../park/pages/Team/RunAdmin";
import { ConnectionsSection as S_19 } from "../park/pages/Team/RunAdmin";
import type { ScreenProps } from "./routes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** A client whose run has recorded events up to and including `seq`, all at once. */
function runUpTo(seq: number): TiloClient {
  const client = new FixtureClient();
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of EVENTS_VILLAGE_BASIC) if (e.seq <= seq) onEvent(e);
    return () => undefined;
  };
  return client;
}

async function text(Screen: (p: ScreenProps) => React.ReactElement, seq: number) {
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(
      <ClientProvider client={runUpTo(seq)}>
        <Screen params={[]} />
      </ClientProvider>,
    );
  });
  return container;
}

describe("AGW-08 S-18 questions waiting follow approval.requested and approval.resolved", () => {
  const waiting = async (seq: number) =>
    (await text(S_18, seq)).querySelectorAll('[data-testid="lead-queue"] li').length;
  it("is 0 before seq 34, 1 from the request until the answer, 0 after", async () => {
    expect(await waiting(33)).toBe(0);
    expect(await waiting(34)).toBe(1);
    expect(await waiting(36)).toBe(1);
    expect(await waiting(37)).toBe(0);
    expect(await waiting(44)).toBe(0);
  });
  it("never lists a card of another run", async () => {
    const page = await text(S_18, 44);
    expect(page.textContent).not.toContain("pack sizes");
    expect(page.textContent).toContain("No question is waiting.");
  });
});

describe("AGW-08 S-19 consent requests come only from connection.requested events", () => {
  it("says none is waiting when the run recorded no consent request", async () => {
    expect((await text(S_19, 44)).textContent).toContain("No access request is waiting.");
  });

  /** The village stream's first event reshaped into one connection event. */
  const conn = (seq: number, type: string, data: object): Event => ({
    ...(EVENTS_VILLAGE_BASIC[0] as Event),
    id: `01JB5VQ00000000000000099${String(seq).padStart(2, "0")}`,
    seq,
    type,
    summary: `${type} ${seq}`,
    data,
  });
  const withEvents = async (events: Event[]) => {
    const client = new FixtureClient();
    client.subscribeEvents = (_world, onEvent) => {
      for (const e of events) onEvent(e);
      return () => undefined;
    };
    const container = document.createElement("div");
    document.body.append(container);
    await act(async () => {
      createRoot(container).render(
        <ClientProvider client={client}>
          <S_19 />
        </ClientProvider>,
      );
    });
    return container.textContent ?? "";
  };
  const requested = conn(1, "connection.requested", { connector: "google_drive", card_id: "c1" });

  it("lists a request until it is answered", async () => {
    expect(await withEvents([requested])).toContain("Google Drive");
  });
  it("stops listing it once its card is consented", async () => {
    const consented = conn(2, "connection.consented", {
      connector: "google_drive",
      card_id: "c1",
      scopes: ["Create files"],
    });
    expect(await withEvents([requested, consented])).toContain("No access request is waiting.");
  });
  it("stops listing it once its connector is revoked (that event has no card id)", async () => {
    const revoked = conn(2, "connection.revoked", { connector: "google_drive" });
    expect(await withEvents([requested, revoked])).toContain("No access request is waiting.");
  });
  it("keeps a request that another connector's revocation did not answer", async () => {
    const other = conn(2, "connection.revoked", { connector: "gmail" });
    expect(await withEvents([requested, other])).toContain("Google Drive");
  });
});

describe("AGW-08 S-17 lists are told apart by registered fields, not by fixture ids", () => {
  it("shows the draft once its send is asked about, and the sent reply once sent", async () => {
    const before = (await text(S_17, 33)).textContent ?? "";
    expect(before).toContain("Nothing has been sent yet.");
    expect(before).toContain("No draft has been written yet.");
    const after = (await text(S_17, 38)).textContent ?? "";
    expect(after).toContain("The reply went to the supplier in the same thread.");
    expect(after).toContain("Thursday 3pm works");
  });
  it("shows the time saved only once world.completed is recorded", async () => {
    expect((await text(S_17, 43)).textContent).toContain("No time-saved estimate yet.");
    expect((await text(S_17, 44)).textContent).toContain("About 8 to 18 min saved (estimate)");
  });
});
