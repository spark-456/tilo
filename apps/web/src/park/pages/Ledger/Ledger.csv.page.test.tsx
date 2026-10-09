// @vitest-environment happy-dom
// FR-SPD-08 on the page: the Export CSV button hands the browser a real file whose rows are the Activity rows the
// page shows, named honestly (sample data says so) and toasting without any accounting-sync claim.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../../test-support/park/appHarness";
import { cleanup, click, mount, qa } from "../../../../test-support/park/componentsHarness";
import { decisions } from "../../api/fixtures";
import { ParkProvider, useApp, useParkStore } from "../../app/context";
import type { ParkStore } from "../../app/store";
import { LedgerPage } from "./LedgerPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
});

function Shell({ onStore }: { onStore: (s: ParkStore) => void }) {
  const app = useApp();
  onStore(useParkStore());
  return (
    <div data-park="" data-time={app.time}>
      <LedgerPage app={app} />
    </div>
  );
}

const settle = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });

describe("FR_SPD_08 ledger export on the page", () => {
  it("FR_SPD_08 page: Export CSV downloads a sample-named file with a header and the page's rows, and does not claim an accounting sync", async () => {
    window.history.pushState({}, "", "/park/ledger");
    const blobs: Blob[] = [];
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: (b: Blob) => {
          blobs.push(b);
          return "blob:ledger-page-test";
        },
        revokeObjectURL: vi.fn(),
      }),
    );
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      names.push(this.download);
    });
    let held: ParkStore | undefined;
    const m = mount(
      <ParkProvider
        api={fakeApi()}
        navigate={vi.fn()}
        schedule={fakeScheduler().schedule}
        viewport={{ vw: 1440, vh: 900 }}
      >
        <Shell
          onStore={(s) => {
            held = s;
          }}
        />
      </ParkProvider>,
    );
    const store = held;
    if (!store) throw new Error("the shell did not mount");
    act(() => store.setDecisions(decisions));
    await settle();

    const button = qa<HTMLElement>(m.container, "button").find(
      (b) => (b.textContent ?? "").trim() === "Export CSV",
    );
    if (!button) throw new Error("no Export CSV button");
    click(button);

    expect(names).toHaveLength(1);
    expect(names[0]).toMatch(/^tilo-ledger-september-2026-sample\.csv$/);
    const csv = (await blobs[0]?.text()) ?? "";
    const lines = csv.replace(/^﻿/, "").trimEnd().split("\r\n");
    expect(lines[0]).toBe("Date,Time,Type,Entry,Where,Amount,Currency,Details");
    expect(lines.length).toBeGreaterThan(1);
    const message = store.getState().toast?.message ?? "";
    expect(message).toContain(names[0] as string);
    expect(message).toContain("sample data");
    expect(message).not.toMatch(/xero|synced/i);
  });
});
