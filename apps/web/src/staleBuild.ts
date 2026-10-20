// A Tilo tab left open keeps running the code it first loaded, so a fix deployed since then never reaches it (live
// 20 Oct: the owner kept seeing a layout fixed hours earlier). When the person comes back to the tab, compare this
// bundle's sha with the one the live page names and reload once if they differ. Never while hidden, never in "dev".
import { BUILD_SHA } from "./park/app/buildStamp";

const META = /<meta[^>]+name="tilo-build"[^>]+content="([0-9a-z]{3,40})"/;

export function differentBuild(liveSha: string | null, ownSha: string = BUILD_SHA): boolean {
  if (!liveSha || ownSha === "dev") return false;
  return !(liveSha.startsWith(ownSha) || ownSha.startsWith(liveSha));
}

export async function liveBuildSha(fetcher: typeof fetch = fetch): Promise<string | null> {
  try {
    const response = await fetcher("/", { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) return null;
    return META.exec(await response.text())?.[1] ?? null;
  } catch {
    return null;
  }
}

export function watchForNewBuild(): void {
  if (BUILD_SHA === "dev" || typeof document === "undefined") return;
  let checking = false;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || checking) return;
    checking = true;
    void liveBuildSha()
      .then((sha) => {
        if (differentBuild(sha)) window.location.reload();
      })
      .finally(() => {
        checking = false;
      });
  });
}
