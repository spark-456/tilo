// @vitest-environment happy-dom
// P0-SKILLS-TEACH: "teach Tilo to ..." typed on Home opens Teach with the words in it; the recorder stops itself under
// the size Tilo can read; the review keeps the cursor while a step is typed.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { MODES } from "../../../../test-support/park/homeCopy";
import {
  clickEl,
  control,
  goCalls,
  lastGo,
  mountHome,
  taskInput,
  typeInto,
} from "../../../../test-support/park/homeHarness";
import { handTeach, takeTeach, teachIntent } from "../../chat/handoff";
import { RECORDING_BYTES, recordScreen } from "../../shared/screenRecorder";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  takeTeach();
});

describe("P0_SKILLS_TEACH_teach_intent", () => {
  it.each([
    ["Teach Tilo to: every Monday, read my unread Gmail", "every Monday, read my unread Gmail"],
    ["teach tilo to summarise the weekly report", "summarise the weekly report"],
    ["Please teach Tilo how to file receipts\nthen email me", "file receipts\nthen email me"],
    ["teach tilo - open the sheet and total it", "open the sheet and total it"],
  ])("%s", (query, words) => {
    expect(teachIntent(query)).toBe(words);
  });

  it.each(["Plan a launch", "teach", "Teach Tilo", "Can you teach Tilo to sing", "teach tilo to"])(
    "is not a teach request: %s",
    (query) => {
      expect(teachIntent(query)).toBeNull();
    },
  );

  it("hands the words over once", () => {
    handTeach("  read my mail ");
    expect(takeTeach()).toBe("read my mail");
    expect(takeTeach()).toBeNull();
  });
});

describe("P0_SKILLS_TEACH_home", () => {
  it("Start on 'teach Tilo to: ...' goes to Skills with the words handed over, not a task", async () => {
    const rig = await mountHome();
    typeInto(taskInput(rig.el), "Teach Tilo to: every Monday, read my unread Gmail");
    clickEl(control(rig.el, MODES[0]?.start ?? ""));
    expect(lastGo(rig.app)?.[0]).toBe("skills");
    expect(goCalls(rig.app)).toBe(1);
    expect(takeTeach()).toBe("every Monday, read my unread Gmail");
  });
});

describe("P0_SKILLS_TEACH_recorder", () => {
  it("stops by itself when the chunks reach the size Tilo can read", async () => {
    const video = { stop: vi.fn(), addEventListener: vi.fn() };
    const display = { getVideoTracks: () => [video], getTracks: () => [video] };
    vi.stubGlobal("navigator", { mediaDevices: { getDisplayMedia: vi.fn(async () => display) } });
    vi.stubGlobal(
      "MediaStream",
      class {
        constructor(public tracks: unknown[]) {}
      },
    );
    let recorder: { send: (n: number) => void; started?: number | undefined } | null = null;
    vi.stubGlobal(
      "MediaRecorder",
      class {
        state = "recording";
        ondataavailable?: (e: { data: Blob }) => void;
        onstop?: () => void;
        constructor() {
          recorder = {
            send: (n) => this.ondataavailable?.({ data: new Blob([new Uint8Array(n)]) }),
          };
        }
        start(slice: number) {
          if (recorder) recorder.started = slice;
        }
        stop() {
          this.state = "inactive";
          this.onstop?.();
        }
      },
    );
    const onStop = vi.fn();
    await recordScreen(false, onStop);
    const rec = recorder as unknown as { send: (n: number) => void; started?: number | undefined };
    expect(rec.started).toBe(1000);
    rec.send(RECORDING_BYTES - 10);
    expect(onStop).not.toHaveBeenCalled();
    rec.send(20);
    expect(onStop).toHaveBeenCalledOnce();
    expect((onStop.mock.calls[0]?.[0] as File).size).toBeLessThan(10_485_760);
  });
});
