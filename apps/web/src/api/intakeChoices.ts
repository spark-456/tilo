/** FR-INT-04/06: the server accepts labels separated by semicolons, never numeric option positions. */
export const pickedLabels = (
  answer: string | null | undefined,
  choices: readonly string[],
): string[] =>
  answer == null
    ? []
    : choices.includes(answer)
      ? [answer]
      : answer.split("; ").filter((label) => choices.includes(label));

export function toggleLabel(
  answer: string | null | undefined,
  choices: readonly string[],
  label: string,
): string {
  const picked = new Set(pickedLabels(answer, choices));
  if (picked.has(label)) picked.delete(label);
  else picked.add(label);
  return choices.filter((choice) => picked.has(choice)).join("; ");
}
