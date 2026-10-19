// Joins class names, skipping the falsy ones (WEB-2). The stylesheet is park.components.css.
export function cx(...names: ReadonlyArray<string | false | null | undefined>): string {
  return names.filter(Boolean).join(" ");
}
