// STARTER-1: the Worlds page's two controls for the sample project. "Hide sample project" while it is listed,
// "Show sample project" when it is not (hidden, or an owner with worlds of their own, for whom the server lists it
// only on request). The choice is this browser's (sampleChoice.ts); nothing is sent to the server but the read.
import { Button } from "../components";
import "./sample.css";

export function SampleControls({
  listed,
  onHide,
  onShow,
}: { listed: boolean; onHide: () => void; onShow: () => void }) {
  return (
    <div className="park-sample-controls">
      {listed ? (
        <Button variant="secondary" size="sm" onClick={onHide}>
          Hide sample project
        </Button>
      ) : (
        <Button variant="secondary" size="sm" onClick={onShow}>
          Show sample project
        </Button>
      )}
    </div>
  );
}
