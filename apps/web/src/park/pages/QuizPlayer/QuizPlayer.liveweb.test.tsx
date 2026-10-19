// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { createLiveApi } from "../../api/liveApi";
import { withToday } from "../../api/sampleDates";
import { withSession } from "../../api/select";
import { QUIZ_FIXTURE_SPEC } from "../../app/appspec.draft";
import { ParkProvider } from "../../app/context";
import { QuizPlayerPage } from "./QuizPlayerPage";

afterEach(cleanup);
describe("Live quiz owner transport", () => {
  it("reads the authenticated owner route through every Api wrapper and renders plain text", async () => {
    const spec = structuredClone(QUIZ_FIXTURE_SPEC);
    spec.title = "Stored practice";
    const question = spec.questions[0];
    if (!question) throw new Error("Missing quiz fixture question");
    question.stem = "<script>window.compromised=true</script> Question";
    const requests: { url: string; init?: RequestInit | undefined }[] = [];
    const fakeFetch: typeof fetch = async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(
        JSON.stringify({
          spec,
          publishers: { [question.source.artifact.artifact_id]: "source.example" },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    };
    const live = createLiveApi({
      baseUrl: "https://api.example",
      fetch: fakeFetch,
      authToken: async () => "owner-token",
      appCheckToken: async () => "app-token",
    });
    const api = withToday(
      withSession(live, {
        demo: () => false,
        identity: () => ({ name: "Owner", email: "owner@example.test" }),
        now: () => new Date("2026-10-11T00:00:00Z"),
      }),
      () => ({ y: 2026, m: 10, d: 11 }),
    );
    let mounted: ReturnType<typeof mount> | undefined;
    await act(async () => {
      mounted = mount(
        <ParkProvider api={api}>
          <QuizPlayerPage worldId="w_live" artifactId="art_quiz" />
        </ParkProvider>,
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    if (!mounted) throw new Error("Player did not mount");
    const request = requests.find((r) => r.url.endsWith("/worlds/w_live/apps/art_quiz"));
    expect(request).toBeDefined();
    expect(new Headers(request?.init?.headers).get("Authorization")).toBe("Bearer owner-token");
    expect(new Headers(request?.init?.headers).get("X-Firebase-AppCheck")).toBe("app-token");
    expect(mounted.container.textContent).toContain("Stored practice");
    expect(mounted.container.textContent).toContain("source.example");
    expect(mounted.container.querySelector('[data-testid="quiz-stem"]')?.textContent).toContain(
      "<script>",
    );
    expect(mounted.container.querySelector("script")).toBeNull();
    expect(mounted.container.querySelector('[data-testid="quiz-unavailable"]')).toBeNull();
  });
  it("a refused owner route leaves no sample questions", async () => {
    const api = createLiveApi({
      baseUrl: "https://api.example",
      fetch: async () => new Response("{}", { status: 404 }),
    });
    let mounted: ReturnType<typeof mount> | undefined;
    await act(async () => {
      mounted = mount(
        <ParkProvider api={api}>
          <QuizPlayerPage worldId="w_live" artifactId="art_quiz" />
        </ParkProvider>,
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    if (!mounted) throw new Error("Player did not mount");
    expect(mounted.container.querySelector('[data-testid="quiz-stem"]')).toBeNull();
    expect(mounted.container.textContent).not.toContain("Computer Science Practice Set");
  });
});
