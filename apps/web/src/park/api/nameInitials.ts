/** Display initials use letters only; punctuation, digits and emoji have no initial. */
export function nameInitials(name: string): string {
  const words = name
    .normalize("NFC")
    .split(/\s+/)
    .map((word) => word.match(/\p{L}/gu) ?? [])
    .filter((letters) => letters.length > 0);
  const first = words[0];
  if (!first) return "?";
  return (
    words.length > 1 ? `${first[0]}${words.at(-1)?.[0]}` : first.slice(0, 2).join("")
  ).toUpperCase();
}
