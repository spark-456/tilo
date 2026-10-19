// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { TiloApiError } from "../../../api/http";
import { ParkProvider, useApp } from "../../app/context";
import { LedgerPage } from "./LedgerPage";
afterEach(cleanup);
function Page() {
  return <LedgerPage app={useApp()} />;
}
it("NFR22 Ledger maps detail and Retry repeats only the read in a reserved box", async () => {
  const api = fakeApi();
  let resolve: (() => void) | undefined;
  api.getLedger = vi
    .fn()
    .mockRejectedValueOnce(new TiloApiError("not_configured", 503, true))
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = () => done({ source: "live", data: { budget: 0, spent: 0 } });
        }),
    );
  let root: ReturnType<typeof mount> | undefined;
  await act(async () => {
    root = mount(
      <ParkProvider api={api} schedule={fakeScheduler().schedule}>
        <Page />
      </ParkProvider>,
    );
  });
  if (!root) throw new Error("Ledger did not mount");
  const box = root.container.querySelector<HTMLElement>("[data-api-read-state]");
  expect(box).not.toBeNull();
  expect(box?.textContent).toContain("This feature is not configured on this server.");
  expect(box?.style.blockSize).toBe("176px");
  const retry = box?.querySelector("button");
  expect(retry?.textContent).toBe("Retry");
  await act(async () => {
    retry?.click();
  });
  expect(api.getLedger).toHaveBeenCalledTimes(2);
  expect(root.container.querySelector<HTMLElement>("[data-api-read-state]")?.style.blockSize).toBe(
    "176px",
  );
  expect(root.container.querySelector("button")?.disabled).toBe(true);
  expect(resolve).toBeTypeOf("function");
});
