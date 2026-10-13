// The "Sample data" chip (plan section 6.1, honesty): shown in the nav whenever a result was read from the
// fixture Api, so sample numbers never pass as live. Its popover says what the sample is. Not part of the
// reference design (BQ-WEB honesty rule), so it is as small as it can be: the StatusChip component, and
// at narrow widths only its dot (the name stays "Sample data" for assistive technology).
import { useState } from "react";
import { Popover, StatusChip } from "../components";

/** What the sample is, in the team's own name (from the user the Api returned). */
export const sampleNote = (org: string | null): string =>
  `${org ?? "This team"} is a fictional team. Amounts are examples (£), dates follow today.`;

/** `ghost`: the same box, invisible and out of the accessibility tree, held where the chip will appear. */
export function SampleChip({
  ghost = false,
  org = null,
}: { ghost?: boolean; org?: string | null }) {
  const [open, setOpen] = useState(false);
  if (ghost) {
    return (
      <span aria-hidden="true" className="park-shell__sample park-shell__booting">
        <StatusChip tone="neutral">
          <span className="park-shell__sampledot" />
          <span className="park-shell__samplelabel">Sample data</span>
        </StatusChip>
      </span>
    );
  }
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        className="park-shell__sample"
        onClick={() => setOpen((v) => !v)}
      >
        <StatusChip tone="neutral">
          <span className="park-shell__sampledot" aria-hidden="true" />
          <span className="park-shell__samplelabel">Sample data</span>
        </StatusChip>
      </button>
      {open ? (
        <Popover label="Sample data" width={320} onClose={() => setOpen(false)}>
          <div className="park-shell__samplebox">
            <span className="park-shell__poptitle">Sample data</span>
            <p className="park-shell__samplenote">{sampleNote(org)}</p>
          </div>
        </Popover>
      ) : null}
    </>
  );
}
