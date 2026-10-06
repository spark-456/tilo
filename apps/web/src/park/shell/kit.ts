// THROWAWAY (WEB-3b validation only): one kit per document.
import { createElement } from "react";
import { plans } from "../api/fixtures/worlds";
import { createKit } from "../engines/kit";
import type { H } from "../engines/types";

let kit: ReturnType<typeof createKit> | null = null;
export const getKit = (): ReturnType<typeof createKit> => {
  kit ??= createKit(createElement as unknown as H, { plans });
  return kit;
};
