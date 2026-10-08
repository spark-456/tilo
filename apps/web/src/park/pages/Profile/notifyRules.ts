// FR-SET-02 pure rules for the notification matrix and quiet hours.
// 1. Decisions always keep at least one channel. 2. Quiet hours silence the phone only; they never hide a
// gate: a gate that cannot be pushed waits in "Needs you" until the person opens Tilo.
export type NotifyEventId = "decisions" | "spend" | "finished" | "digest" | "weekly";
/** The cells of one matrix row, in column order: phone, email, slack. */
export type Cells = readonly boolean[];
export type Reach = "pushed" | "waiting" | "off";

/** A gate is an event that needs a person; today that is the "decisions" row. */
export const isGate = (id: NotifyEventId): boolean => id === "decisions";

/** May this channel be switched off? Not when it is the last channel of a decision event. */
export function canSwitchOff(id: NotifyEventId, row: Cells, channel: number): boolean {
  return !(isGate(id) && row[channel] === true && row.filter(Boolean).length === 1);
}

/**
 * What happens to an event during quiet hours. Quiet hours silence the phone (except a gate over the
 * threshold); email and Slack are unaffected. A gate that is not pushed is "waiting" (still shown in
 * Needs you), never "off"; "off" means the person chose no channel for a non-gate event.
 */
export function reachDuringQuiet(input: {
  id: NotifyEventId;
  channels: Cells;
  quietOn: boolean;
  overThreshold: boolean;
}): Reach {
  const [phone, email, slack] = input.channels;
  const gate = isGate(input.id);
  const phoneAllowed = !input.quietOn || (gate && input.overThreshold);
  if ((phone && phoneAllowed) || email || slack) return "pushed";
  if (gate || phone) return "waiting";
  return "off";
}
