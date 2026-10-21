// UX-SMOOTH: Start was pressed; the World page and the live stage code download while the server answers, so the
// page opens on cached code instead of fetching (and evaluating) it after the answer. The same imports the route and
// the World page use; a failed speculative request is left for their own boundaries to report.
export function prefetchLiveWorld(): void {
  void import("../pages/World/WorldPage").catch(() => undefined);
  void import("../../worldView/LiveStageEmbed").catch(() => undefined);
}
