import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import Icon from "./Icons";
import { Badge, Btn, StatusBadge, TypeBadge } from "./UI";
import { useLive } from "../context/LiveContext";
import { useAction } from "../hooks/useApi";
import { eventApi, mediaUrl, reportApi } from "../services/api";
import { cap, fmtClock, fmtDateTime, fmtDuration, pct } from "../utils/format";

export function AiSummary({ event }) {
  if (!event.summary) return <span className="muted">Summary is generated when recording completes.</span>;
  if (event.summary_source === "gemini") {
    return <p style={{ margin: 0, lineHeight: 1.6 }}>{event.summary}</p>;
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="note" style={{ color: "var(--amber)" }}>
        AI summary unavailable.{event.summary_error ? <span className="muted"> {event.summary_error}</span> : null}
      </div>
      <p style={{ margin: 0, lineHeight: 1.6 }}><span className="muted">Rule-based description: </span>{event.summary}</p>
    </div>
  );
}

/** Event details in a modal – video, snapshot, facts, AI summary, Play / Download / PDF. */
export default function EventModal({ event, onClose, autoplay = false }) {
  const { toast } = useLive();
  const { busy, run } = useAction(toast);
  const videoRef = useRef(null);
  const e = event;

  useEffect(() => {
    const onKey = (ev) => ev.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(() => { if (autoplay) videoRef.current?.play().catch(() => {}); }, [autoplay, e?.id]);
  if (!e) return null;

  const pdf = () => run("pdf", async () => {
    const r = await reportApi.generate(e.id);
    window.open(reportApi.downloadUrl(r.id, true), "_blank");
    return r;
  }, (r) => `PDF report #${r.id} generated`);

  return (
    <div className="modal-backdrop" onMouseDown={(ev) => ev.target === ev.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={`Event ${e.id}`}>
        <div className="panel-head">
          <div className="row" style={{ gap: 10 }}>
            <h2>Event <span className="mono">#{e.id}</span></h2>
            <TypeBadge type={e.event_type} /><StatusBadge status={e.status} />
            {e.video_offset != null && <Badge tone="cyan">{fmtClock(e.video_offset)} in video</Badge>}
          </div>
          <Btn className="ghost sm" icon="x" onClick={onClose} aria-label="Close" />
        </div>
        <div className="modal-body">
          <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.5fr) minmax(0,1fr)" }}>
            <div className="stack">
              {e.video_url ? (
                <div className="feed"><video ref={videoRef} src={mediaUrl(e.video_url)} controls preload="metadata" poster={mediaUrl(e.snapshot_url)} /></div>
              ) : <div className="note">Event clip is still being encoded…</div>}
              <div className="row">
                <Btn icon="play" onClick={() => videoRef.current?.play()} disabled={!e.video_url}>Play</Btn>
                <a className={`btn ${e.video_url ? "" : "disabled"}`} href={e.video_url ? eventApi.downloadUrl(e.id) : undefined}><Icon name="download" />Download Video</a>
                <Btn icon="report" className="primary" busy={busy === "pdf"} disabled={e.status !== "completed"} onClick={pdf}>Generate PDF</Btn>
                <Link className="btn ghost" to={`/events/${e.id}`}>Full details →</Link>
              </div>
              <div>
                <h3 style={{ marginBottom: 8 }}>AI summary</h3>
                <AiSummary event={e} />
              </div>
            </div>
            <div className="stack">
              {e.snapshot_url && <img src={mediaUrl(e.snapshot_url)} alt="Event snapshot" style={{ width: "100%", borderRadius: 8, border: "1px solid var(--line)" }} />}
              <dl className="kv">
                <dt>Event type</dt><dd><TypeBadge type={e.event_type} /></dd>
                <dt>Object</dt><dd>{cap(e.object_class) || "—"}</dd>
                <dt>Confidence</dt><dd className="mono">{pct(e.confidence)}</dd>
                <dt>Zone</dt><dd>{e.zone_name || "—"}</dd>
                <dt>Start time</dt><dd className="mono">{fmtDateTime(e.start_time)}</dd>
                <dt>End time</dt><dd className="mono">{fmtDateTime(e.end_time)}</dd>
                <dt>Duration</dt><dd className="mono">{fmtDuration(e.duration)}</dd>
                {e.video_offset != null && <><dt>Video time</dt><dd className="mono">{fmtClock(e.video_offset)}</dd></>}
                {e.analysis_name && <><dt>Source video</dt><dd>{e.analysis_name}</dd></>}
              </dl>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
