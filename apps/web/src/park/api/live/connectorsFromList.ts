import { nameInitials } from "../nameInitials";
import type { Connector } from "../types";

/** FR-ACC-01/03/04, HR-1: only fields GET /v1/connectors serves; unknown state stays unknown. */
export function connectorsFromList(body: unknown): Connector[] | null {
  if (
    !body ||
    typeof body !== "object" ||
    !("connectors" in body) ||
    !Array.isArray(body.connectors)
  )
    return null;
  const rows: Connector[] = [];
  for (const c of body.connectors) {
    if (
      !c ||
      typeof c !== "object" ||
      typeof c.id !== "string" ||
      !c.id ||
      typeof c.name !== "string" ||
      !c.name ||
      !["connected", "attention", "available"].includes(c.state) ||
      typeof c.state_known !== "boolean" ||
      !Array.isArray(c.scopes) ||
      !c.scopes.every((s: unknown) => typeof s === "string") ||
      !(c.expires_at === null || typeof c.expires_at === "string")
    )
      return null;
    rows.push({
      id: c.id,
      name: c.name,
      st: c.state,
      cat: "",
      mono: nameInitials(c.name),
      col: "var(--ink2)",
      live: { stateKnown: c.state_known, scopes: [...c.scopes] },
      ...(c.expires_at === null ? {} : { expires: c.expires_at }),
    });
  }
  return rows;
}
