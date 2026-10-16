/** Small event-bound bob while an agent is walking; reduced motion keeps only the recorded slide. */
export const walkBob = (progress: number, reducedMotion: boolean): number =>
  reducedMotion ? 0 : Math.sin(Math.max(0, Math.min(1, progress)) * Math.PI * 8) * 1.35;
