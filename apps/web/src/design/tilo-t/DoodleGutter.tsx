// The side doodle wallpaper as a gutter background (design/tilo-t). Decoration only: hidden from assistive tech, hidden below
// 1200px, and drawn only outside the content column (see doodles.css). Mount it once per app page, as the first child of the
// themed root.
import "./doodles.css";

export function DoodleGutter() {
  return <div className="tt-doodles" aria-hidden="true" data-testid="tt-doodles" />;
}
