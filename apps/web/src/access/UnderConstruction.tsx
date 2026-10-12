// SEC-15: what a visitor sees. No form, no upload, no way into the product: the server refuses every call.
import { AccessScreen } from "./AccessScreen";
export function UnderConstruction() {
  return (
    <AccessScreen>
      <div data-testid="under-construction">
        <h1>Tilo is still under construction</h1>
        <p>
          Tilo is still under construction and not open to the public yet. Please check back later.
        </p>
      </div>
    </AccessScreen>
  );
}
