// Owner-only quiz reading travels with the Api through its session wrappers.
// This capability leaves the pinned phase-zero Api method contract unchanged.
import type { Api } from "./index";
export interface QuizView {
  readonly spec: unknown;
  readonly publishers: Readonly<Record<string, string>>;
}
export type QuizReader = (worldId: string, artifactId: string) => Promise<QuizView>;
const readers = new WeakMap<Api, QuizReader>();
export const installQuizReader = (api: Api, reader: QuizReader): void => {
  readers.set(api, reader);
};
export function carryQuizReader(from: Api, to: Api, enabled: () => boolean = () => true): Api {
  const reader = readers.get(from);
  if (reader)
    installQuizReader(to, (world, artifact) => {
      if (!enabled()) return Promise.reject(new Error("Quiz unavailable"));
      return reader(world, artifact);
    });
  return to;
}
export function readQuizApp(api: Api, world: string, artifact: string): Promise<QuizView> {
  const reader = readers.get(api);
  return reader ? reader(world, artifact) : Promise.reject(new Error("Quiz unavailable"));
}
