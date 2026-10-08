// The reply of `POST /v1/meetings/{id}/host` (services/api meeting_host.py, FR-MTG-09), and the check
// that a body has that shape before anything is shown as started. The reply carries only the meeting's
// world id: the T3 gate card is posted to that world's card list, never inside the reply.

export interface HostStarted {
  readonly world_id: string;
}

/** Whether a reply is the documented `{world_id}`; anything else is not shown as a started run. */
export const isHostStarted = (v: unknown): v is HostStarted => {
  const id = (v as Partial<HostStarted> | null)?.world_id;
  return typeof id === "string" && id.length > 0;
};

/** The word a refusal carries, only when it is a short token: the connector's rule (`MH-02`) or the API's
 * reason (`not_hostable`, `already_hosted`, `not_found`, `not_configured`). Free text is never kept. */
export function refusalOf(text: string): string | null {
  try {
    const body = JSON.parse(text) as { detail?: unknown; rule?: unknown } | null;
    const { detail, rule } = body ?? {};
    if (typeof rule === "string" && /^MH-\d{2}$/.test(rule)) return rule;
    return typeof detail === "string" && /^[a-z][a-z0-9_]{0,39}$/.test(detail) ? detail : null;
  } catch {
    return null;
  }
}
