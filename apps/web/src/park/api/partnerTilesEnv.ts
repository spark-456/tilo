// PREP-CONNECTORS-TILES: opt-in display only; no API or provider activation.
export function partnerTilesEnabled(value: unknown): boolean {
  return value === "true";
}

export function showPartnerTiles(): boolean {
  return partnerTilesEnabled(
    typeof document === "undefined"
      ? undefined
      : document.querySelector('meta[name="tilo-partner-tiles"]')?.getAttribute("content"),
  );
}
