import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import AnalysisTimeline from "../components/AnalysisTimeline";
import EventModal from "../components/EventModal";
import Icon from "../components/Icons";
import { Badge, Btn, Empty, ErrorBox, PageHead, Panel, Stat, TypeBadge } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useAction, useApi } from "../hooks/useApi";
import { eventApi, reportApi, videoAnalysisApi } from "../services/api";
import { cap, fmtBytes, fmtClock, fmtDateTime, fmtDuration, pct } from "../utils/format";
import { StatusPill } from "./VideoAnalysis";

const ACTIVE = ["queued", "processing"];

function Progress({ a }) {
  const pctDone = Math.round(a.progress);
  return (
    <Panel title={<span className="row">{a.status === "queued" ? "Waiting to start…" : "Analyzing video…"} <StatusPill status={a.status} /></span>}>
      <div className="row between" style={{ marginBottom: 8 }}>
        <span className="muted">{a.stage || "—"}</span>
        <span className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{pctDone}%</span>
      </div>
      <div className="meter big"><div style={{ width: `${a.progress}%` }} /></div>
      <div className="grid g-4" style={{ marginTop: 16, gap: 12 }}>
        <div><div className="kv-label">Frames processed</div><div className="mono">{a.frames_processed} / {a.total_frames}</div></div>
        <div><div className="kv-label">Current timestamp</div><div className="mono">{fmtClock(a.current_time)} / {fmtClock(a.duration)}</div></div>
        <div><div className="kv-label">Objects detected</div><div className="mono">{a.objects_detected}</div></div>
        <div><div className="kv-label">YOLO passes</div><div className="mono">{a.detections_run}</div></div>
        <div><div className="kv-label">Events detected</div><div className="mono">{a.events_detected}</div></div>
        <div><div className="kv-label">Zone violations</div><div className="mono">{a.zone_violations}</div></div>
        <div><div className="kv-label">Loitering events</div><div className="mono">{a.loitering_events}</div></div>
        <div><div className="kv-label">Elapsed</div><div className="mono">{fmtDuration(a.processing_seconds)}</div></div>
      </div>
    </Panel>
  );
}

export default function AnalysisDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { toast } = useLive();
  const { busy, run } = useAction(toast);
  const videoRef = useRef(null);
  const [time, setTime] = useState(0);
  const [modal, setModal] = useState(null);
  const analysis = useApi(() => videoAnalysisApi.get(id), [id]);
  const a = analysis.data;
  const active = a && ACTIVE.includes(a.status);
  const events = useApi(() => videoAnalysisApi.events(id), [id, a?.status, a?.events_detected], { initial: [] });

  // the browser-playable preview of the upload is encoded in the background – refresh until it exists
  useEffect(() => {
    if (!a || a.preview_ready) return undefined;
    const t = setInterval(() => analysis.reload(true), 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a?.preview_ready]);

  // poll progress while the job is queued/processing
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(async () => {
      try {
        const st = await videoAnalysisApi.status(id);
        analysis.setData((prev) => ({ ...prev, ...st }));
        if (!ACTIVE.includes(st.status)) analysis.reload(true);
      } catch { /* transient – next tick retries */ }
    }, 1000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, active]);

  const seek = useCallback((e) => {
    if (videoRef.current && e.video_offset != null) {
      videoRef.current.currentTime = Math.max(0, e.video_offset - 1);
    }
  }, []);
  const open = (e, autoplay = false) => { seek(e); setModal({ event: e, autoplay }); };

  if (analysis.error) return <><PageHead title="Video analysis" /><ErrorBox error={analysis.error} /></>;
  if (!a) return <Empty title="Loading…" />;

  const startRun = (force) => run("start", async () => { await videoAnalysisApi.start(a.analysis_id, force); await analysis.reload(true); },
    force ? "Re-analysis started" : "Analysis started");
  const cancel = () => run("cancel", async () => { await videoAnalysisApi.cancel(a.analysis_id); await analysis.reload(true); }, "Cancelling analysis…");
  const remove = () => {
    if (!window.confirm(`Delete the uploaded video "${a.original_name}"?`)) return;
    const withEvents = events.data.length > 0 && window.confirm(
      `Also delete the ${events.data.length} event(s) found in it (clips, snapshots, reports)?\n\nOK = delete them · Cancel = keep them in Events`);
    run("delete", async () => { await videoAnalysisApi.remove(a.analysis_id, withEvents); nav("/video-analysis"); }, "Video deleted");
  };
  const pdf = (e) => run(`pdf${e.id}`, async () => {
    const r = await reportApi.generate(e.id);
    window.open(reportApi.downloadUrl(r.id, true), "_blank");
    return r;
  }, (r) => `PDF report #${r.id} generated`);

  const finished = a.status === "completed" || a.status === "cancelled" || (a.status === "failed" && a.frames_processed > 0);
  return (
    <>
      <PageHead title={<span className="row" style={{ gap: 12 }}><span style={{ wordBreak: "break-all" }}>{a.original_name}</span><StatusPill status={a.status} /></span>}
        subtitle={`Analysis #${a.analysis_id} · ${fmtClock(a.duration)} · ${a.width}×${a.height} · ${a.fps} fps · ${a.total_frames} frames · ${fmtBytes(a.size_bytes)}`}>
        <Link to="/video-analysis" className="btn ghost">← Videos</Link>
        {a.status === "uploaded" && <Btn icon="play" className="primary" busy={busy === "start"} onClick={() => startRun(false)}>Start Analysis</Btn>}
        {active && <Btn icon="x" className="danger" busy={busy === "cancel"} disabled={a.stage === "cancelling"} onClick={cancel}>Cancel</Btn>}
        {["completed", "failed", "cancelled"].includes(a.status) && <Btn icon="restart" busy={busy === "start"} onClick={() => startRun(a.status === "completed")}>Re-analyse</Btn>}
        {!active && <Btn icon="trash" className="ghost" busy={busy === "delete"} onClick={remove} />}
      </PageHead>

      {a.status === "failed" && <div style={{ marginBottom: 16 }}><ErrorBox error={a.error} /></div>}
      {a.warning && <div className="note" style={{ marginBottom: 16, color: "var(--amber)" }}>{a.warning}</div>}
      {a.status === "cancelled" && <div className="note" style={{ marginBottom: 16 }}>Analysis was cancelled at {fmtClock(a.current_time)} ({Math.round(a.progress)}%). Events found up to that point are kept.</div>}
      {active && <div style={{ marginBottom: 16 }}><Progress a={a} /></div>}

      {a.status === "completed" && (
        <div className="complete-banner"><Icon name="check" size={18} /> VIDEO ANALYSIS COMPLETE
          <span className="muted" style={{ fontWeight: 400, letterSpacing: 0 }}>· {a.frames_processed} frames in {fmtDuration(a.processing_seconds)} · YOLO ran on {a.detections_run} frames (motion-gated)</span></div>
      )}
      {(finished || active) && (
        <div className="grid g-5" style={{ marginBottom: 16 }}>
          <Stat label="Total events" value={a.events_detected} />
          <Stat label="Persons detected" value={a.persons_detected} hint="unique tracked people" accent="var(--green)" />
          <Stat label="Vehicles detected" value={a.vehicles_detected} hint="car · motorcycle · bus · truck · bicycle" accent="#a78bfa" />
          <Stat label="Zone violations" value={a.zone_violations} accent="var(--amber)" />
          <Stat label="Loitering events" value={a.loitering_events} accent="var(--red)" />
        </div>
      )}

      <div className="grid g-live" style={{ marginBottom: 16 }}>
        <Panel title="Original video" actions={<a className="btn sm ghost" href={videoAnalysisApi.originalUrl(a.analysis_id)}>Download original</a>}>
          <div className="feed" style={{ aspectRatio: `${a.width || 16} / ${a.height || 9}` }}>
            <video key={a.preview_ready ? "preview" : "original"} ref={videoRef} src={videoAnalysisApi.videoUrl(a.analysis_id, a.preview_ready)} controls preload="metadata"
              onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} />
          </div>
          {!a.preview_ready && <div className="note" style={{ marginTop: 8 }}>Preparing a browser-playable preview of this file… If the player stays black, use “Download original”.</div>}
          <div style={{ marginTop: 14 }}>
            <AnalysisTimeline duration={a.duration} events={events.data} currentTime={time} selectedId={modal?.event?.id} onSelect={(e) => open(e)} />
          </div>
        </Panel>
        <Panel title="Event timeline" pad={false} actions={<span className="muted mono">{events.data.length}</span>}>
          {!events.data.length ? <Empty title={active ? "No events yet" : "No events detected"}>{active ? "Events appear here as soon as they are recorded." : "No relevant objects, zone entries or loitering were found with the current settings."}</Empty> : (
            <ul className="timeline" style={{ padding: "6px 16px" }}>
              {events.data.map((e) => (
                <li key={e.id} className="clickable-row" onClick={() => open(e)}>
                  <span className="t">{fmtClock(e.video_offset)}</span>
                  <span className={`pin ${{ object_detection: "", zone_violation: "amber", loitering: "red", motion: "slate" }[e.event_type]}`} />
                  <div>
                    <div className="row" style={{ gap: 6 }}><TypeBadge type={e.event_type} /><span>{cap(e.object_class) || "Motion"}</span>{e.zone_name && <span className="muted">@ {e.zone_name}</span>}</div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{fmtDuration(e.duration)} · {pct(e.confidence)}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel title="Events from this video" pad={false} actions={<Link className="btn sm ghost" to={`/events?analysis_id=${a.analysis_id}`}>Open in Events →</Link>}>
        {!events.data.length ? <Empty title={active ? "Waiting for events…" : "No events"} /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Time</th><th>Event type</th><th>Object</th><th>Zone</th><th>Confidence</th><th>Duration</th><th>Summary</th><th>Actions</th></tr></thead>
              <tbody>
                {events.data.map((e) => (
                  <tr key={e.id}>
                    <td className="mono" style={{ whiteSpace: "nowrap" }}>{fmtClock(e.video_offset)}<div className="faint" style={{ fontSize: 11.5 }}>{fmtDateTime(e.start_time)}</div></td>
                    <td><TypeBadge type={e.event_type} /></td>
                    <td>{cap(e.object_class) || "—"}</td>
                    <td>{e.zone_name || <span className="faint">—</span>}</td>
                    <td className="mono">{pct(e.confidence)}</td>
                    <td className="mono">{fmtDuration(e.duration)}</td>
                    <td className="muted" style={{ minWidth: 220, maxWidth: 300, fontSize: 12.5 }}>
                      {e.summary_source && e.summary_source !== "gemini" && <div><Badge>AI summary unavailable</Badge></div>}
                      <div className="clamp-3" title={e.summary || ""}>{e.summary || e.status}</div>
                    </td>
                    <td className="actions-cell">
                      <div className="actions-grid">
                        <Btn className="sm ghost" icon="eye" onClick={() => open(e)}>View</Btn>
                        <Btn className="sm ghost" icon="play" disabled={!e.video_url} onClick={() => open(e, true)}>Play</Btn>
                        <a className={`btn sm ghost ${e.video_url ? "" : "disabled"}`} href={e.video_url ? eventApi.downloadUrl(e.id) : undefined}><Icon name="download" />Download</a>
                        <Btn className="sm ghost" icon="report" busy={busy === `pdf${e.id}`} disabled={e.status !== "completed"} onClick={() => pdf(e)}>PDF</Btn>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {modal && <EventModal event={events.data.find((e) => e.id === modal.event.id) || modal.event} autoplay={modal.autoplay} onClose={() => setModal(null)} />}
    </>
  );
}
