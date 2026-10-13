import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { expect, it } from "vitest";

it("MR_01 the checked-in room validator matches the unchanged contract schemas", () => {
  const script = join(__dirname, "../../../../scripts/generate-room-guard.mjs");
  const result = spawnSync(process.execPath, [script, "--check"], { encoding: "utf8" });
  expect(result.stderr).toBe("");
  expect(result.status).toBe(0);
});

it("MR_01 SEC_01 validates recorded rooms with runtime code generation disabled by hosting CSP", () => {
  const module = pathToFileURL(join(__dirname, "meetingRoom.guard.js")).href;
  const source = `import validate from ${JSON.stringify(module)};
    const room = {room_id:'01ARZ3NDEKTSV4RRFFQ69G5FAV',world_id:'w_one',run_id:'r_one',state:'open',reason:null,lead:'A_one',agents:[],as_role:'owner',credit_cap:5,credits_spent:0,max_turns:10,turns:[]};
    if (!validate(room) || validate({...room,credits_spent:'zero'})) process.exit(1);`;
  const result = spawnSync(
    process.execPath,
    ["--disallow-code-generation-from-strings", "--input-type=module", "--eval", source],
    { encoding: "utf8" },
  );
  expect(result.stderr).toBe("");
  expect(result.status).toBe(0);
});
