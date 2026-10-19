// FR-WLD-13: sample only the existing event-driven animation loop. No clock, timer or events.
export function createMobileQuality() {
  let shadows = true;
  let start: number | null = null;
  let frames = 0;
  return {
    get shadows() {
      return shadows;
    },
    idle() {
      start = null;
      frames = 0;
    },
    sample(now: number, width: number) {
      if (width > 600) {
        shadows = true;
        start = null;
        frames = 0;
        return;
      }
      if (!Number.isFinite(now) || !shadows) return;
      if (start === null || now < start) {
        start = now;
        frames = 0;
        return;
      }
      frames++;
      const elapsed = now - start;
      if (elapsed >= 1000) {
        if ((frames * 1000) / elapsed < 30) shadows = false;
        start = now;
        frames = 0;
      }
    },
  };
}
