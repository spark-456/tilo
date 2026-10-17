const DATE_ONLY_HOUR = 12;
const SCHEDULE_LEAD_MINUTES = 5;
const SLOT_MINUTES = 15;

export function agendaDateLabel(value: string): string {
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const date = dateOnly
    ? (() => {
        const [year, month, day] = value.split("-").map(Number);
        return new Date(year ?? 0, (month ?? 1) - 1, day ?? 1, DATE_ONLY_HOUR);
      })()
    : new Date(value);
  if (Number.isNaN(date.getTime())) return "Date not supplied";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const day = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(date);
  const time = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(
    date,
  );
  return sameDay ? `Today ${time}` : `${day}${dateOnly ? "" : ` · ${time}`}`;
}

export function defaultAgendaScheduleStart(): string {
  const next = new Date(Date.now() + SCHEDULE_LEAD_MINUTES * 60_000);
  next.setMinutes(Math.ceil(next.getMinutes() / SLOT_MINUTES) * SLOT_MINUTES, 0, 0);
  return next.toISOString();
}

export function agendaLocalDateTime(value: string): string {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
