// The boundary around every code-split screen (NFR-01): see the class.
import { Component, type ReactNode } from "react";

/** A screen's chunk did not arrive (offline, or a deploy replaced its name). A browser keeps a failed
 * dynamic import for the life of the page, so asking again in place cannot work: say so and offer a
 * reload, which also picks up a redeployed chunk's new name (NFR-01, like the stage's own chunk). */
export class ChunkBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="screen-loading" role="alert" data-testid="screen-chunk-failed">
        <p>This page did not load.</p>
        <button type="button" className="secondary" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
