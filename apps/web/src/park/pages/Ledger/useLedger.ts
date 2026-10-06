// Loads the Ledger through the Park Api and keeps its `source`, so the page can say whether it shows sample
// data (HR-1..HR-7). A NotBuilt rejection (the live Api before its endpoint exists) is its own state:
// the page shows "Not connected yet", never fixture numbers.
import { useEffect, useState } from "react";
import type { Api } from "../../api/index";
import { NotBuilt } from "../../api/liveApi";
import type { Ledger, Source } from "../../api/types";

export type LedgerState =
  | { status: "loading" }
  | { status: "ready"; data: Ledger; source: Source }
  | { status: "not-built" }
  | { status: "error" };

export function useLedger(api: Api): LedgerState {
  const [state, setState] = useState<LedgerState>({ status: "loading" });
  useEffect(() => {
    let live = true;
    api.getLedger().then(
      (r) => live && setState({ status: "ready", data: r.data, source: r.source }),
      (e: unknown) => live && setState({ status: e instanceof NotBuilt ? "not-built" : "error" }),
    );
    return () => {
      live = false;
    };
  }, [api]);
  return state;
}
