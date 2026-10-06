// TEMPORARY local stand-in for the shared `useParkApi()` (helper contract, plan section 10): the page
// reads the Park Api through it. The shared hook arrives with WEB-3a (park/app) and this file is deleted.
// It always returns the fixture Api (`source: "fixture"`, so the page and the shell say "Sample data"):
// the repo test test_P0_07c pins api/ClientProvider.tsx as the only reader of the live-switch variable,
// so the env switch (`parkApi(env)`) belongs to the shared hook.
import type { Api } from "../../api/index";
import { parkApi } from "../../api/select";

let shared: Api | undefined;

export function useParkApi(): Api {
  shared ??= parkApi({});
  return shared;
}
