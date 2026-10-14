import { ParkProvider, useApp, useHasParkProvider } from "../app/context";
import { AppearanceControls } from "../pages/Profile/AppearanceControls";
import "../tokens/park.css";
import "../tokens/park.opaque.css";
import "../tokens/themes.css";

function Controls({ standalone = false }: { standalone?: boolean }) {
  const app = useApp();
  const controls = <AppearanceControls app={app} />;
  return standalone ? (
    <div data-park data-time={app.time} style={{ minHeight: 0, background: "transparent" }}>
      {controls}
    </div>
  ) : (
    controls
  );
}

export function SettingsAppearance() {
  const hasPark = useHasParkProvider();
  return hasPark ? (
    <Controls />
  ) : (
    <ParkProvider>
      <Controls standalone />
    </ParkProvider>
  );
}
