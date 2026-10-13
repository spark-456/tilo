// UI-10 W7: preserve the Settings controls inside the Park shell and its single main.
import { S_22 } from "../../../screens/S_22";
import { PageSheet } from "../../components";

export function SettingsPage() {
  return (
    <div data-testid="park-page-settings">
      <PageSheet>
        <S_22 />
      </PageSheet>
    </div>
  );
}
