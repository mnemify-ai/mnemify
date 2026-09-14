// The backend scheduler runs cron in UTC, but nobody thinks in UTC — presets
// are named in the user's local time and converted to a UTC cron on the spot.
// (Stored crons are fixed UTC instants, so they won't shift with DST.)

/** Daily cron at `localHour`:00 in the user's local time, expressed in UTC. */
export function dailyUtcCron(localHour: number): string {
  const d = new Date();
  d.setHours(localHour, 0, 0, 0);
  return `${d.getUTCMinutes()} ${d.getUTCHours()} * * *`;
}

/** Weekly cron on `localWeekday` at `localHour`:00 local time, expressed in UTC. */
export function weeklyUtcCron(localWeekday: number, localHour: number): string {
  const d = new Date();
  d.setDate(d.getDate() + ((localWeekday - d.getDay() + 7) % 7));
  d.setHours(localHour, 0, 0, 0);
  return `${d.getUTCMinutes()} ${d.getUTCHours()} * * ${d.getUTCDay()}`;
}

/** The "every morning" preset shared by Settings and the Home briefing card. */
export const MORNING_HOUR_LOCAL = 6;
export const morningUtcCron = () => dailyUtcCron(MORNING_HOUR_LOCAL);
