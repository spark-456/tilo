// PREP-CONNECTORS-TILES: preparation requirements only, never connection state.
// No catalogue entry, credential read, status request or activation action.
import { Card, StatusChip } from "../../components";
import "./PartnerTiles.css";

const partners = [
  { name: "Canva", status: "Needs the workspace owner's Canva app" },
  { name: "Slack", status: "Needs the workspace owner's Slack app" },
  { name: "Lovable MCP", status: "Needs the workspace owner's Lovable app" },
] as const;

export function PartnerTiles() {
  return (
    <section className="park-partner-tiles" aria-label="Partner preparation">
      <h2>Partner preparation</h2>
      <p>These partners are not activated. App registration alone does not connect a tool.</p>
      <div className="park-partner-tiles-grid">
        {partners.map((partner) => (
          <Card key={partner.name}>
            <h3>{partner.name}</h3>
            <StatusChip tone="neutral">Not activated</StatusChip>
            <p>{partner.status}</p>
          </Card>
        ))}
      </div>
    </section>
  );
}
