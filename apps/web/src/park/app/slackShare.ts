// Pure helpers for FR-UX-17 (Share a world link to Slack through the approval card). Reads the Slack connector
// from useParkApi().getConnectors(), caps the optional note length, formats the pending approval card copy
// ("Waiting for approval", plus "sample" in sample mode, never "Shared"), and traps keyboard focus in the dialog.
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { Connector } from "../api/types";

export const SLACK_NOTE_MAX = 240;

export interface SlackShareRequest {
  readonly worldId: string;
  readonly worldName: string;
  readonly channel: string;
  readonly note: string;
  readonly sample: boolean;
}

export interface SlackConnectorState {
  readonly connected: boolean;
  readonly account: string;
  readonly channels: readonly string[];
  readonly disabledReason: string;
}

export function capSlackNote(raw: string): string {
  return raw.slice(0, SLACK_NOTE_MAX);
}

export function slackConnectorState(connectors: readonly Connector[]): SlackConnectorState {
  const slack = connectors.find((c) => c.id === "slack" || c.name.toLowerCase() === "slack");
  if (!slack || slack.st !== "connected") {
    const reason =
      slack?.st === "attention"
        ? "Slack needs attention in Connectors before sharing a world link."
        : "Slack is not connected. Connect Slack in Connectors to share a world link.";
    return {
      connected: false,
      account: slack?.acct ?? "Slack",
      channels: [],
      disabledReason: reason,
    };
  }
  const seen = new Set<string>();
  const channels: string[] = [];
  for (const raw of slack.channels ?? []) {
    const ch = raw.trim();
    if (ch && !seen.has(ch)) {
      seen.add(ch);
      channels.push(ch);
    }
  }
  if (channels.length === 0) {
    return {
      connected: false,
      account: slack.acct ?? "Slack",
      channels: [],
      disabledReason: "Slack has no channels available to share into.",
    };
  }
  return {
    connected: true,
    account: slack.acct ?? "Slack",
    channels,
    disabledReason: "",
  };
}

export function slackApprovalStatusLabel(sample: boolean): string {
  return sample ? "Waiting for approval · sample" : "Waiting for approval";
}

export function slackApprovalTitle(channel: string): string {
  return `Slack gate · post world link to ${channel}`;
}

export function slackApprovalBody(req: SlackShareRequest): string {
  const cleanNote = capSlackNote(req.note).trim();
  if (cleanNote.length > 0) {
    return `Post ${req.worldName} link to ${req.channel}. Note: ${cleanNote}`;
  }
  return `Post ${req.worldName} link to ${req.channel}. Nothing sent until approved.`;
}

const FOCUSABLE_SELECTOR =
  'select:not([disabled]), textarea:not([disabled]), input:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function focusablesIn(dialog: HTMLElement | null): HTMLElement[] {
  if (!dialog) return [];
  return Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => !el.hasAttribute("disabled") && el.getAttribute("aria-disabled") !== "true",
  );
}

export function handleSlackDialogKeyDown(
  e: ReactKeyboardEvent<HTMLElement>,
  dialog: HTMLElement | null,
  onClose: () => void,
): void {
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    onClose();
    return;
  }
  if (e.key !== "Tab" || !dialog) return;
  const list = focusablesIn(dialog);
  if (list.length === 0) return;
  const first = list[0];
  const last = list[list.length - 1];
  if (!first || !last) return;
  const active = document.activeElement as HTMLElement | null;
  if (!e.shiftKey && (active === last || !dialog.contains(active))) {
    e.preventDefault();
    first.focus();
  } else if (e.shiftKey && (active === first || !dialog.contains(active))) {
    e.preventDefault();
    last.focus();
  }
}
