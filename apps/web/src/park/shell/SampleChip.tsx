// The "Sample data" chip (plan section 6.1, honesty): shown in the nav whenever a result was read from the
// fixture Api, so sample numbers never pass as live. Its popover says what the sample is. Not part of the
// reference design (BQ-WEB honesty rule), so it is as small as it can be: the StatusChip component, and
// at narrow widths only its dot (the name stays "Sample data" for assistive technology).
import { useState } from "react";
import { Popover, StatusChip } from "../components";

export const SAMPLE_NOTE =
  "Northwind Ops is a fictional team. Amounts are examples (£), dates are September 2026.";

export function SampleChip() {
  const [open, setOpen] = useState(false);
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
            <p className="park-shell__samplenote">{SAMPLE_NOTE}</p>
          </div>
        </Popover>
      ) : null}
    </>
  );
}
