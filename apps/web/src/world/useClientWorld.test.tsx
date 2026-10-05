// @vitest-environment happy-dom
// #264: leaving /world/<id> while the layout is still pending must not throw (Pixi's removeChildren
// refuses a range that starts at the end of a non-empty container), and the layout wait is stopped.
import { Container } from "pixi.js";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import type { TiloClient } from "../api/client";
import type { WorldSeam } from "../stage/Stage";
import { useClientWorld } from "./useClientWorld";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("#264 useClientWorld cleanup while the layout is pending", () => {
  it("does not throw when nothing was added to a container that already has children", async () => {
    let signal: AbortSignal | undefined;
    const client = {
      getLayout: vi.fn((_id: string, s?: AbortSignal) => {
        signal = s;
        return new Promise(() => undefined); // never built
      }),
    } as unknown as TiloClient;
    const world = new Container();
    world.addChild(new Container()); // the stage's own grid is already on it
    const errors: unknown[] = [];
    const onError = (e: ErrorEvent) => errors.push(e.error);
    window.addEventListener("error", onError);

    let seam: WorldSeam | undefined;
    function Probe() {
      seam = useClientWorld(client, "w_pending").onWorld;
      return null;
    }
    const root = createRoot(document.createElement("div"));
    await act(async () => root.render(<Probe />));
    // The stage hands its container over once; the effect then asks for the layout.
    await act(
      async () =>
        void seam?.(
          world,
          () => undefined,
          () => ({ width: 1, height: 1 }),
        ),
    );
    expect(client.getLayout).toHaveBeenCalledOnce();
    await act(async () => root.unmount());
    window.removeEventListener("error", onError);

    expect(errors).toEqual([]);
    expect(world.children).toHaveLength(1);
    expect(signal?.aborted).toBe(true);
  });
});
