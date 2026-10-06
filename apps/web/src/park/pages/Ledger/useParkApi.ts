// TEMPORARY local stand-in for the shared `useParkApi()` (helper contract, plan section 10): the page
// reads the Park Api through it. The shared hook arrives with WEB-3a (park/app); this file is then deleted
// and the import in useLedger.ts points at it. No VITE_TILO_API_URL = the fixture Api, a url = the live
// Api (which rejects with NotBuilt until each endpoint exists). One Api per document.
import type { Api } from "../../api/index";
import { parkApi } from "../../api/select";

let shared: Api | undefined;

export function useParkApi(): Api {
  shared ??= parkApi({ VITE_TILO_API_URL: import.meta.env.VITE_TILO_API_URL });
  return shared;
}
