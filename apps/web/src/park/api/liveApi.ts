// The live Api (WEB-1a): a stub. No endpoint is built yet, so every method rejects with NotBuilt and
// nothing is fetched. It never imports the fixtures, so sample numbers cannot pass as live (HR-1..HR-7).
import { API_METHODS, type Api, type ApiMethod } from "./index";

export class NotBuilt extends Error {
  readonly code = "not_built";
  constructor(method: ApiMethod) {
    super(`${method} is not connected yet`);
    this.name = "NotBuilt";
  }
}

export function createLiveApi(): Api {
  const stubs = API_METHODS.map((m) => [m, () => Promise.reject(new NotBuilt(m))]);
  return Object.fromEntries(stubs) as unknown as Api;
}
