// STARTER-1: the "Sample" badge and its one-line note, shown wherever the sample project appears (Home, the
// Worlds row, the world page). Text only; nothing moves.
import "./sample.css";
import { SAMPLE_NOTE } from "./sampleChoice";

export function SampleBadge() {
  return <span className="park-sample-badge">Sample</span>;
}

export function SampleNote({ className }: { className?: string }) {
  return (
    <span className={className ? `park-sample-note ${className}` : "park-sample-note"}>
      {SAMPLE_NOTE}
    </span>
  );
}
