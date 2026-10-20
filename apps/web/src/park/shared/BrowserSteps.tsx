// DEMO-BROWSER: what Tilo's browser did in a run, as a short ordered list for its result (opened X, searched Y, read Z).
// Only recorded browser.acted events that were done (HR-1); a scroll is not a step; the host is all an event names
// (BR-13: never a full address or the words searched).
import type { BrowserActedData } from "@tilo/contracts";
import "./BrowserPanel.css";

type StepEvent = { seq: number; type: string; data?: unknown; summary?: string };

const MAX_SHOWN = 10;

function stepOf(data: BrowserActedData): string | null {
  const caption = data.caption ?? "";
  const host = data.host ?? "the page";
  if (data.kind === "extract")
    return caption.startsWith("Searching") ? `Searched ${host}` : `Read ${host}`;
  if (data.kind === "navigate")
    return caption.startsWith("Searching") ? `Searched ${host}` : `Opened ${host}`;
  if (data.kind === "click") return caption.replace(/^Clicking\b/, "Clicked");
  if (data.kind === "type") return caption.replace(/^Typing\b/, "Typed");
  return null;
}

export function browserSteps(events: readonly StepEvent[]): string[] {
  const steps: string[] = [];
  for (const event of events) {
    if (event.type !== "browser.acted" || !event.data || typeof event.data !== "object") continue;
    const data = event.data as BrowserActedData;
    if (data.verdict !== "done") continue;
    const step = stepOf(data);
    if (step && steps[steps.length - 1] !== step) steps.push(step);
  }
  return steps;
}

export function BrowserSteps({ events }: { events: readonly StepEvent[] }) {
  const steps = browserSteps(events);
  if (steps.length === 0) return null;
  return (
    <section className="tilo-browser-steps" aria-label="What Tilo's browser did">
      <h3>What Tilo's browser did</h3>
      <ol>
        {steps.slice(0, MAX_SHOWN).map((step, index) => (
          <li key={`${index}-${step}`}>{step}</li>
        ))}
      </ol>
      {steps.length > MAX_SHOWN ? <p>{`and ${steps.length - MAX_SHOWN} more steps`}</p> : null}
    </section>
  );
}
