// What the assistant panel asks of its backend (FR-PA-13/14): a question and the screen's context in,
// an answer with the records it came from out. The real adapter reads the deterministic read models;
// until those exist the fixture adapter answers every question with an honest "preview" notice and
// never makes an answer up. No model, search or send is reachable from here (PL-01, EFF-01).

/** Where the person is: the screen's short name, its address, and the selected record if any. */
export interface AssistantContext {
  readonly label: string;
  readonly route: string;
  readonly record: string | null;
}

/** A record an answer is based on, for the link under it. */
export interface AssistantSource {
  readonly label: string;
  readonly href: string;
}

export interface AssistantReply {
  readonly text: string;
  readonly sources: readonly AssistantSource[];
}

export interface AssistantAdapter {
  ask(question: string, context: AssistantContext): Promise<AssistantReply>;
}

export const fixtureAdapter: AssistantAdapter = {
  async ask(_question, context) {
    return {
      text: `This is a preview of the assistant panel. It is not connected to your plate, tasks, cards or calendar yet, so it cannot answer. You are on ${context.label}.`,
      sources: [],
    };
  },
};
