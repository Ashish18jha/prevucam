export const EVENT_TYPES = {
  object_detection: { label: "Object", tone: "cyan" },
  zone_violation: { label: "Zone violation", tone: "amber" },
  loitering: { label: "Loitering", tone: "red" },
  motion: { label: "Motion", tone: "slate" },
};

export const typeLabel = (t) => EVENT_TYPES[t]?.label ?? t;
export const typeTone = (t) => EVENT_TYPES[t]?.tone ?? "slate";

export function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
export function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
export function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" });
}
export function fmtDuration(s) {
  if (s == null) return "—";
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}
export function fmtBytes(b) {
  if (b == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = b;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}
export const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
export const todayISO = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
export const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/** Position inside a video: 83.4 -> "01:23", 3725 -> "1:02:05". */
export function fmtClock(sec) {
  if (sec == null || Number.isNaN(sec)) return "--:--";
  const t = Math.max(0, Math.round(sec));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}
export const VEHICLES = ["car", "motorcycle", "bus", "truck", "bicycle"];
