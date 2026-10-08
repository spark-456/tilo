// FR-CON-16: Lovable URL builder and contract size-cap enforcement for the World page.
// Mirrors services/connectors/src/tilo_connectors/adapters/lovable.py and config/build_partners.yaml:
// - URL prefix: `https://lovable.dev/#prompt=`
// - Max prompt length: 50,000 characters
// - Max total URL length: 32,000 characters
// - Refuses (returns null) when empty or over either limit; never truncates the prompt (BH-06).

export const LOVABLE_LINK_PREFIX = "https://lovable.dev/#prompt=";
export const MAX_LOVABLE_PROMPT_CHARS = 50_000;
export const MAX_LOVABLE_URL_LENGTH = 32_000;

export interface LovableLimits {
  maxPromptChars?: number;
  maxUrlLength?: number;
}

/**
 * Builds the `https://lovable.dev/#prompt=...` URL with `encodeURIComponent` and enforces
 * the contract's prompt and total URL size caps. Returns `null` if the prompt is empty or
 * exceeds either cap.
 */
export function buildLovableUrl(prompt: string, limits: LovableLimits = {}): string | null {
  const maxPrompt = limits.maxPromptChars ?? MAX_LOVABLE_PROMPT_CHARS;
  const maxUrl = limits.maxUrlLength ?? MAX_LOVABLE_URL_LENGTH;
  if (prompt.length === 0 || prompt.length > maxPrompt) return null;
  const url = `${LOVABLE_LINK_PREFIX}${encodeURIComponent(prompt)}`;
  if (url.length > maxUrl) return null;
  return url;
}
