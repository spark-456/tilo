import type { RunPhase } from "./runView";

interface DirectionClient {
  pauseWorld(worldId: string): Promise<void>;
  startAgain(worldId: string, direction: string): Promise<{ world_id: string; task_id: string }>;
}

/** The rerun route accepts direction after the current run has stopped. */
export async function redirectDirection(
  client: DirectionClient,
  worldId: string,
  instruction: string,
  phase: RunPhase | null,
  isPaused: boolean,
) {
  if (phase && !["none", "paused", "done", "failed"].includes(phase) && !isPaused) {
    await client.pauseWorld(worldId);
  }
  return client.startAgain(worldId, instruction);
}
