// WEB-LEGAL: the two public legal pages. Dependency-free on purpose: Root is the entry chunk and imports this
// to decide whether to load the (lazy) legal page. A trailing slash is tolerated, as in keptPaths.ts.
export type LegalKind = "privacy" | "terms";

/** `privacy` for /privacy, `terms` for /terms, otherwise null (`window.location.pathname`). */
export const legalKind = (pathname: string): LegalKind | null => {
  const m = /^\/(privacy|terms)\/?$/.exec(pathname);
  return m ? (m[1] as LegalKind) : null;
};
