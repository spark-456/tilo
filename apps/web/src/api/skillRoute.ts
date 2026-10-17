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

export interface CatalogSkill {
  readonly id: string;
  readonly kind: "library" | "taught";
  readonly scope: "library" | "mine" | "team";
  readonly name: string;
  readonly purpose: string;
  readonly inputs: readonly unknown[];
  readonly tools: readonly string[];
  readonly version: string | number;
}

export interface SkillRef {
  readonly kind: "skill" | "taught_skill";
  readonly id: string;
}
export const skillRefOf = (skill: Pick<CatalogSkill, "id" | "kind">): SkillRef => ({
  kind: skill.kind === "library" ? "skill" : "taught_skill",
  id: skill.id,
});

/** The catalog is untrusted network data; malformed entries never enter the picker. */
export function catalogOf(value: unknown): CatalogSkill[] {
  if (!value || typeof value !== "object" || !Array.isArray((value as { skills?: unknown }).skills))
    return [];
  return (value as { skills: unknown[] }).skills.slice(0, 60).filter((row): row is CatalogSkill => {
    if (!row || typeof row !== "object") return false;
    const s = row as Record<string, unknown>;
    return (
      typeof s.id === "string" &&
      s.id.length > 0 &&
      typeof s.name === "string" &&
      s.name.length > 0 &&
      typeof s.purpose === "string" &&
      (s.kind === "library" || s.kind === "taught") &&
      (s.scope === "library" || s.scope === "mine" || s.scope === "team") &&
      Array.isArray(s.inputs) &&
      Array.isArray(s.tools) &&
      s.tools.every((t) => typeof t === "string") &&
      (typeof s.version === "string" || typeof s.version === "number")
    );
  });
}

/** A mention opens only while the person is typing its final token. */
export function mentionQuery(text: string): string | null {
  const match = /(?:^|\s)@([^\s@]*)$/.exec(text);
  return match ? (match[1] ?? "") : null;
}

/** One send seam maps the served catalog choice to the API's id-only ref. */
export function sendWithSkill<T>(
  text: string,
  skill: Pick<CatalogSkill, "id" | "kind"> | null,
  send: (text: string, ref: SkillRef | null) => T,
): T {
  return send(text, skill ? skillRefOf(skill) : null);
}
