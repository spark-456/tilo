// The design fonts the shell draws with, loaded before the shell is shown. The nav, the popovers and the
// loader are in Nunito 800/900 and Nunito Sans 400/600/700/800; if they arrive after the first paint the
// text swaps from the fallback face and the nav moves (layout shift). The boot splash stays until this
// settles. Only promises here: a face that fails to load must not hold the app, so failures are ignored.
const FACES = [
  '800 16px "Nunito"',
  '900 27px "Nunito"',
  '400 14px "Nunito Sans"',
  '600 14px "Nunito Sans"',
  '700 14px "Nunito Sans"',
  '800 14px "Nunito Sans"',
  // UI-STUDIO-1: the Studio theme (the default) draws the same chrome in Geist.
  '500 15px "Geist Sans"',
  '600 15px "Geist Sans"',
  '700 15px "Geist Sans"',
  '800 26px "Geist Sans"',
] as const;

export function loadShellFonts(): Promise<void> {
  const set = typeof document === "undefined" ? undefined : document.fonts;
  if (!set) return Promise.resolve();
  const settled = FACES.map((face) => set.load(face).then(noop, noop));
  return Promise.all(settled).then(noop);
}

function noop(): void {}
