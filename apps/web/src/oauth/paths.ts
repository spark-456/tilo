// ADR-0035 LC-01: the address Google sends the browser back to. Dependency-free on purpose: Root is the entry chunk and
// imports this to decide whether to load the (lazy) callback page. A trailing slash is tolerated, as in keptPaths.ts.
export const isOAuthCallback = (pathname: string): boolean =>
  /^\/oauth\/google\/callback\/?$/.test(pathname);
