import { type TiloRole, roleColor } from "../design/tilo-t/role";

const ROLE_OF_RANK: Readonly<Record<string, TiloRole>> = {
  director: "director",
  lead: "delivery",
  specialist: "research",
  writer: "designer",
  verifier: "tester",
  narrator: "finance",
};

export const agentRoleOf = (rank: string): TiloRole => ROLE_OF_RANK[rank] ?? "builder";
export const agentRoleColor = (rank: string): string => roleColor(agentRoleOf(rank));
