import { useMemo } from "react";
import { typeLabel, typeTone, cap, fmtClock } from "../utils/format";

const TONE = { cyan: "var(--cyan)", amber: "var(--amber)", red: "var(--red)", slate: "var(--muted)" };
const LANE_H = 30;

/**
 * Visual event timeline for one uploaded video. Each event is a marker at its position in the
 * video with a bar for its duration; labels are stacked into lanes so they never overlap.
 */
export default function AnalysisTimeline({ duration, events, currentTime = 0, selectedId, onSelect }) {
  const total = Math.max(duration || 0, 1);
  const items = useMemo(() => {
    const lanes = [];
    return [...events]
      .filter((e) => e.video_offset != null)
      .sort((a, b) => a.video_offset - b.video_offset)
      .map((e) => {
        const left = (100 * e.video_offset) / total;
        const width = Math.max(0.6, (100 * (e.duration || 0)) / total);
        const end = left + Math.max(width, 18); // reserve room for the label
        let lane = lanes.findIndex((x) => x <= left);
        if (lane === -1) { lane = lanes.length; lanes.push(end); } else lanes[lane] = end;
        return { e, left, width, lane };
      });
  }, [events, total]);
  const laneCount = Math.max(1, ...items.map((i) => i.lane + 1));
  const ticks = Array.from({ length: 6 }, (_, i) => (total * i) / 5);

  return (
    <div className="va-timeline">
      <div className="va-track" style={{ height: laneCount * LANE_H + 14 }}>
        <div className="va-axis" />
        {items.map(({ e, left, lane }) => {
          const color = TONE[typeTone(e.event_type)];
          return (
            <button key={e.id} type="button" className={`va-marker ${e.id === selectedId ? "on" : ""}`}
              style={{ left: `${left}%`, top: lane * LANE_H + 4, "--c": color }}
              title={`${fmtClock(e.video_offset)} · ${typeLabel(e.event_type)} · ${e.object_class || ""}${e.zone_name ? ` @ ${e.zone_name}` : ""}`}
              onClick={() => onSelect?.(e)}>
              <span className="va-dot" />
              <span className="va-label">{fmtClock(e.video_offset)} · {e.event_type === "object_detection" ? cap(e.object_class) : typeLabel(e.event_type)}</span>
            </button>
          );
        })}
        {items.map(({ e, left, width, lane }) => (
          <span key={`bar${e.id}`} className="va-bar" style={{ left: `${left}%`, width: `${width}%`, top: lane * LANE_H + 12,
            background: TONE[typeTone(e.event_type)] }} />
        ))}
        <span className="va-playhead" style={{ left: `${Math.min(100, (100 * currentTime) / total)}%` }} />
      </div>
      <div className="va-ticks">
        {ticks.map((t, i) => <span key={i} style={{ left: `${(100 * t) / total}%` }}>{fmtClock(t)}</span>)}
      </div>
    </div>
  );
}
