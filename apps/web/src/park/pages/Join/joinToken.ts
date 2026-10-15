/** Keep the bearer only across the sign-in redirect. Run before any gate starts a request. */
export const JOIN_TOKEN_KEY = "tilo.team-invite-link";

export function captureJoinToken(): void {
  if (window.location.pathname !== "/join") return;
  let meta = document.querySelector<HTMLMetaElement>('meta[name="referrer"]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "referrer";
    document.head.append(meta);
  }
  meta.content = "no-referrer";
  const fragment = window.location.hash;
  if (!fragment) return;
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${window.location.search}`,
  );
  if (fragment.length > 1) sessionStorage.setItem(JOIN_TOKEN_KEY, fragment.slice(1));
}
