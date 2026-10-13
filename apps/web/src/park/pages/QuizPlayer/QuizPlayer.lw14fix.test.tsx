// @vitest-environment happy-dom
// LW-14 review fixes (PR #700): the player accepts exactly what contracts/appspec.schema.json accepts, and the
// fictional sample quiz is served only where the shell shows its Sample chip; a live Api gets an honest
// "not available yet" page (HR-1..HR-7). The schema is read here, in the test only: the production bundle carries no
// JSON Schema validator (the page CSP forbids eval), so these tests are what keeps the hand checks in line.
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { createLiveApi } from "../../api/liveApi";
import { QUIZ_FIXTURE_SPEC, validateAppSpec } from "../../app/appspec.draft";
import { ParkProvider } from "../../app/context";
import { QuizPlayerPage } from "./QuizPlayerPage";

afterEach(() => {
  cleanup();
});

const root = `${resolve(process.cwd(), "../../contracts")}/`;
const ajv = new Ajv2020({ strict: false, allErrors: true, validateFormats: false });
for (const file of readdirSync(root, { recursive: true, encoding: "utf8" }))
  if (file.endsWith(".schema.json"))
    ajv.addSchema(JSON.parse(readFileSync(`${root}${file}`, "utf8")));
const schema = ajv.getSchema("https://contracts.tilo.example/appspec.schema.json");

const json = (path: string): unknown => JSON.parse(readFileSync(`${root}${path}`, "utf8"));
const fixtures = (dir: "valid" | "invalid"): [string, unknown][] =>
  readdirSync(`${root}fixtures/appspec/${dir}`).map((f) => [
    f,
    json(`fixtures/appspec/${dir}/${f}`),
  ]);

type Spec = typeof QUIZ_FIXTURE_SPEC;
const withQuestion = (patch: Record<string, unknown>): unknown => {
  const spec = structuredClone(QUIZ_FIXTURE_SPEC) as Spec;
  spec.questions[0] = { ...spec.questions[0], ...patch } as Spec["questions"][number];
  return spec;
};
const source = (artifact: Record<string, unknown>): unknown =>
  withQuestion({ source: { artifact } });

describe("LW_14_fix the player accepts exactly what the schema accepts", () => {
  it("LW_14_fix the schema itself is loaded and the sample quiz is valid under both", () => {
    expect(schema).toBeDefined();
    expect(schema?.(QUIZ_FIXTURE_SPEC)).toBe(true);
    expect(validateAppSpec(QUIZ_FIXTURE_SPEC).ok).toBe(true);
  });

  it("LW_14_fix every contract fixture gets the same verdict from the schema and from the player", () => {
    for (const [name, spec] of [...fixtures("valid"), ...fixtures("invalid")]) {
      expect(validateAppSpec(spec).ok, name).toBe(schema?.(spec) === true);
    }
  });

  it("LW_14_fix slug, artifact id and label edges match the schema (topic 9-x, label of 81 chars)", () => {
    const cases: unknown[] = [
      withQuestion({ topic: "9-x" }),
      withQuestion({ topic: "9abc" }),
      withQuestion({ topic: "a-b" }),
      withQuestion({ topic: "a_b9" }),
      source({ artifact_id: "x", version: 1 }),
      source({ artifact_id: `art_${"a".repeat(49)}`, version: 1 }),
      source({ artifact_id: "art_ok", version: 1, label: "x".repeat(81) }),
      source({ artifact_id: "art_ok", version: 1, label: "x".repeat(80) }),
      source({ artifact_id: "art_ok", version: 1, label: "" }),
      { ...(QUIZ_FIXTURE_SPEC as object), theme: "9-x" },
      { ...(QUIZ_FIXTURE_SPEC as object), theme: "gate_prep" },
    ];
    for (const spec of cases) {
      expect(validateAppSpec(spec).ok, JSON.stringify(spec).slice(0, 160)).toBe(
        schema?.(spec) === true,
      );
    }
    expect(validateAppSpec(withQuestion({ topic: "9-x" })).ok).toBe(false);
    expect(
      validateAppSpec(source({ artifact_id: "art_ok", version: 1, label: "x".repeat(81) })).ok,
    ).toBe(false);
  });

  it("LW_14_fix a spec the schema rejects shows the error screen, not the quiz", () => {
    const m = mount(
      <ParkProvider>
        <QuizPlayerPage worldId="w1" artifactId="art_bad" spec={withQuestion({ topic: "9-x" })} />
      </ParkProvider>,
    );
    expect(m.container.querySelector('[data-testid="quiz-error"]')).not.toBeNull();
    expect(m.container.querySelector('[data-testid="quiz-stem"]')).toBeNull();
  });
});

describe("LW_14_fix the sample quiz is only served where the Sample chip shows", () => {
  it("LW_14_fix under a live Api the page says it is not available yet and shows no sample question", () => {
    const m = mount(
      <ParkProvider api={createLiveApi()}>
        <QuizPlayerPage worldId="w1" artifactId="art_any" />
      </ParkProvider>,
    );
    const note = m.container.querySelector('[data-testid="quiz-unavailable"]');
    expect(note?.textContent ?? "").toContain("This quiz is not available yet");
    expect(m.container.querySelector('[data-testid="quiz-stem"]')).toBeNull();
    expect(m.container.textContent ?? "").not.toContain("iitk");
  });

  it("LW_14_fix an artifact id of 'malformed' is no longer a hook: under the fixture Api it shows the sample quiz", () => {
    const m = mount(
      <ParkProvider>
        <QuizPlayerPage worldId="w1" artifactId="malformed" />
      </ParkProvider>,
    );
    expect(m.container.querySelector('[data-testid="quiz-error"]')).toBeNull();
    expect(m.container.querySelector('[data-testid="quiz-stem"]')).not.toBeNull();
    expect(m.container.textContent ?? "").toContain("Sample");
    expect(m.container.textContent ?? "").not.toContain("Owner only");
  });
});
