import { useNavigate } from "react-router-dom";
import { StatusBadge, TypeBadge } from "./UI";
import { mediaUrl } from "../services/api";
import { cap, fmtClock, fmtDate, fmtDuration, fmtTime, pct } from "../utils/format";

export default function EventTable({ events, compact = false }) {
  const nav = useNavigate();
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th />
            <th>ID</th>
            <th>Type</th>
            <th>Object</th>
            {!compact && <th>Confidence</th>}
            <th>Zone</th>
            {!compact && <th>Source</th>}
            <th>{compact ? "Time" : "Date / time"}</th>
            <th>Duration</th>
            {!compact && <th>Status</th>}
            {!compact && <th>Summary</th>}
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id} className="clickable" onClick={() => nav(`/events/${e.id}`)}>
              <td>{e.snapshot_url ? <img className="thumb" src={mediaUrl(e.snapshot_url)} alt="" loading="lazy" /> : <div className="thumb" />}</td>
              <td className="mono">#{e.id}{e.is_protected && <span title="Protected from retention"> 🔒</span>}</td>
              <td><TypeBadge type={e.event_type} /></td>
              <td>{cap(e.object_class) || "—"}</td>
              {!compact && <td className="mono">{pct(e.confidence)}</td>}
              <td>{e.zone_name || <span className="faint">—</span>}</td>
              {!compact && (
                <td style={{ fontSize: 12.5 }}>
                  {e.source === "video"
                    ? <><span title={e.analysis_name || ""} style={{ display: "inline-block", maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", verticalAlign: "bottom" }}>{e.analysis_name || `analysis #${e.analysis_id}`}</span><div className="mono faint">@ {fmtClock(e.video_offset)}</div></>
                    : <span className="muted">Live camera</span>}
                </td>
              )}
              <td className="mono">{compact ? fmtTime(e.start_time) : <>{fmtDate(e.start_time)} <span className="muted">{fmtTime(e.start_time)}</span></>}</td>
              <td className="mono">{fmtDuration(e.duration)}</td>
              {!compact && <td><StatusBadge status={e.status} /></td>}
              {!compact && <td className="muted" style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.summary || "—"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
