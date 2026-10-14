// The two small wording helpers the world views share (they were the old kit's): machine names never reach the
// screen as they are, and counts get real plurals.

/** "send_email" -> "Send email". */
export const words = (id: string): string =>
  id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** "1 level", "2 levels". */
export const plural = (n: number, one: string, many = `${one}s`): string =>
  `${n} ${n === 1 ? one : many}`;

/** Brand and channel names as people write them. */
const NAMES: Readonly<Record<string, string>> = {
  gmail: "Gmail",
  google_drive: "Google Drive",
  email: "Email",
};
export const nameOf = (id: string): string => NAMES[id] ?? words(id);
