/** Only a skill named by the API may appear in a plan or Quick offer (FR-SKL-04). */
export interface SkillMatch {
  readonly id: string;
  readonly kind: "library" | "taught";
  readonly scope: "library" | "mine" | "team";
  readonly name: string;
  readonly version: string | number;
  readonly score: number;
  readonly source: "matched" | "picked" | "tagged";
}

export function skillMatchOf(value: unknown): SkillMatch | null {
  if (typeof value !== "object" || value === null) return null;
  const s = value as Record<string, unknown>;
  if (
    typeof s.id !== "string" ||
    !s.id ||
    typeof s.name !== "string" ||
    !s.name ||
    !["library", "taught"].includes(String(s.kind)) ||
    !["library", "mine", "team"].includes(String(s.scope)) ||
    !["matched", "picked", "tagged"].includes(String(s.source)) ||
    (typeof s.version !== "string" && typeof s.version !== "number") ||
    typeof s.score !== "number" ||
    !Number.isFinite(s.score) ||
    s.score < 0 ||
    s.score > 1
  )
    return null;
  return s as unknown as SkillMatch;
}
