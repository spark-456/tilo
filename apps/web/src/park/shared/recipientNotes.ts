/** MINUTES-ALL security review (21 Oct): what to point out about one address on an email card the person approves.
 * Every address is shown in full; these notes sit beside the ones that deserve a second look. Display only: the
 * server decides who may be sent to, and nothing is sent until the person approves the card. */

export function domainOf(address: string): string | null {
  const at = address.lastIndexOf("@");
  return at > 0 && at < address.length - 1 ? address.slice(at + 1).toLowerCase() : null;
}

export interface Known {
  /** The signed-in person's own address, whose domain is "yours". */
  readonly ownerEmail: string | null;
  /** The addresses on record for the meeting's attendees (and the person themself); null when not known here. */
  readonly attendees?: ReadonlySet<string> | null;
}

export function recipientNotes(address: string, known: Known): string[] {
  const notes: string[] = [];
  const domain = domainOf(address);
  if (!domain) return notes;
  if (known.attendees && !known.attendees.has(address.toLowerCase()))
    notes.push("Not an attendee on record");
  const own = known.ownerEmail ? domainOf(known.ownerEmail) : null;
  if (own && domain !== own) notes.push(`Outside your domain (${domain})`);
  return notes;
}
