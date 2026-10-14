// PREP-CONNECTORS-TILES: opt-in display only; no API or provider activation.
export function partnerTilesEnabled(value: unknown): boolean {
  return value === "true";
}

export function showPartnerTiles(): boolean {
  return partnerTilesEnabled(import.meta.env.VITE_TILO_PARTNER_TILES);
}
