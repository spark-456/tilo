// FR-AGT-14 (PRD 8, "Scheduled runs"): the optional "Repeat weekly" control of the confirm card, ported from the
// retired S-03. Off by default. When it is on, Start posts one schedule after the budget grant and the start succeed.
// The weekday is 0 = Monday (the API's Cadence), the time zone is the browser's own.
import { type ReactElement, useId, useState } from "react";
import { type Cadence, WEEKDAYS } from "../../api/oneStep";

const TIME = /^([01]\d|2[0-3]):([0-5]\d)$/;

const browserZone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
};

export interface Repeat {
  readonly on: boolean;
  /** The cadence to post, or null when it is off or the time is not a valid HH:MM. */
  readonly cadence: Cadence | null;
  /** The person asked for a repeat the card cannot post yet (an invalid time): Start waits. */
  readonly invalid: boolean;
  readonly control: ReactElement;
}

export function useRepeatWeekly(disabled: boolean): Repeat {
  const [on, setOn] = useState(false);
  const [weekday, setWeekday] = useState("0");
  const [time, setTime] = useState("09:00");
  const [tz] = useState(browserZone);
  const id = useId();
  const parts = TIME.exec(time);
  const cadence: Cadence | null =
    on && parts
      ? { weekday: Number(weekday), hour: Number(parts[1]), minute: Number(parts[2]), tz }
      : null;
  const control = (
    <div className="park-home-repeat" data-testid="repeat-weekly-block">
      <label className="park-home-repeat__toggle">
        <input
          type="checkbox"
          data-testid="repeat-weekly"
          checked={on}
          disabled={disabled}
          onChange={(e) => setOn(e.target.checked)}
        />
        <span>Repeat weekly</span>
      </label>
      {on ? (
        <fieldset className="park-home-repeat__fields" aria-label="Repeat weekly">
          <label htmlFor={`${id}-day`}>Day</label>
          <select
            id={`${id}-day`}
            data-testid="repeat-weekday"
            value={weekday}
            disabled={disabled}
            onChange={(e) => setWeekday(e.target.value)}
          >
            {WEEKDAYS.map((name, i) => (
              <option key={name} value={String(i)}>
                {name}
              </option>
            ))}
          </select>
          <label htmlFor={`${id}-time`}>Time</label>
          <input
            id={`${id}-time`}
            data-testid="repeat-time"
            type="time"
            value={time}
            disabled={disabled}
            aria-invalid={parts === null}
            aria-describedby={parts === null ? `${id}-hint` : undefined}
            onChange={(e) => setTime(e.target.value)}
          />
          <span className="park-home-repeat__tz">
            Time zone: <output data-testid="repeat-tz">{tz}</output>
          </span>
          {parts === null ? (
            <span id={`${id}-hint`} className="park-home-repeat__hint">
              Enter a time such as 09:00.
            </span>
          ) : null}
        </fieldset>
      ) : null}
    </div>
  );
  return { on, cadence, invalid: on && parts === null, control };
}
