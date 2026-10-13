/**
 * Dates are stored and passed around as text, exactly as SQLite stores them:
 * 'YYYY-MM-DD' for dates and 'YYYY-MM-DD HH:MM:SS' (naive UTC) for datetimes.
 * Working on strings avoids the timezone traps of JS Date round-trips.
 */

const DAY_MS = 86_400_000;

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function nowText(): string {
  return new Date().toISOString().slice(0, 19).replace("T", " ");
}

export function isValidDate(iso: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return false;
  const d = new Date(`${iso}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === iso;
}

function toUtc(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`);
}

/** Whole days from `a` to `b` (b - a). */
export function daysBetween(a: string, b: string): number {
  return Math.round((toUtc(b) - toUtc(a)) / DAY_MS);
}

export function addDays(iso: string, days: number): string {
  return new Date(toUtc(iso) + days * DAY_MS).toISOString().slice(0, 10);
}

export function eachDay(start: string, end: string): string[] {
  const out: string[] = [];
  for (let i = 0; i <= daysBetween(start, end); i++) out.push(addDays(start, i));
  return out;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Oct 13" */
export function shortDate(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${MONTHS[Number(m) - 1]} ${Number(d)}`;
}

/** "Oct 13, 2026" */
export function longDate(iso: string): string {
  return `${shortDate(iso)}, ${iso.slice(0, 4)}`;
}

/** Datetimes render in Berkeley local time, like the old |localtime filter. */
export function localDateTime(text: string | null): string {
  if (!text) return "";
  const date = new Date(`${text.replace(" ", "T")}Z`);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-US", {
    timeZone: "America/Los_Angeles",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
