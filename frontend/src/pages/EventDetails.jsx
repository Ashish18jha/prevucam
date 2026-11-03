import { useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge, Btn, Empty, ErrorBox, PageHead, Panel, StatusBadge, Switch, TypeBadge } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useAction, useApi } from "../hooks/useApi";
import { eventApi, mediaUrl, reportApi } from "../services/api";
import { AiSummary } from "../components/EventModal";
import { cap, fmtClock, fmtBytes, fmtDate, fmtDateTime, fmtDuration, fmtTime, pct, typeTone } from "../utils/format";

export default function EventDetails() {
  const { id } = useParams();
  const nav = useNavigate();
  const { toast, eventTick } = useLive();
  const videoRef = useRef(null);
  const ev = useApi(() => eventApi.get(id), [id, eventTick]);
  const reports = useApi(() => reportApi.list({ event_id: id }), [id], { initial: [] });
  const { busy, run } = useAction(toast);
  const e = ev.data;

  if (ev.error) return <><PageHead title={`Event #${id}`} /><ErrorBox error={ev.error} /></>;
  if (!e) return <Empty title="Loading…" />;
  const meta = e.metadata_json || {};
  const processing = e.status === "recording" || e.status === "processing";

  const play = () => { videoRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }); videoRef.current?.play(); };
  const genReport = () => run("report", async () => {
    const r = await reportApi.generate(e.id);
    await reports.reload(true);
    window.open(reportApi.downloadUrl(r.id, true), "_blank");
    return r;
  }, (r) => `Report #${r.id} generated`);
  const notify = () => run("notify", () => eventApi.notify(e.id),
    (res) => res.map((r) => `${r.channel}: ${r.status}${r.detail ? ` (${r.detail})` : ""}`).join(" · "));
  const summarize = () => run("summary", async () => ev.setData(await eventApi.regenerateSummary(e.id)), "Summary regenerated");
  const protect = (v) => run("protect", async () => ev.setData(await eventApi.update(e.id, { is_protected: v })), v ? "Event protected from retention" : "Protection removed");
  const remove = () => {
    if (!window.confirm(`Delete event #${e.id} and its video, snapshot and reports?`)) return;
    run("delete", async () => { await eventApi.remove(e.id); nav("/events"); }, `Event #${e.id} deleted`);
  };

  return (
    <>
      <PageHead title={<span className="row" style={{ gap: 12 }}>Event <span className="mono">#{e.id}</span> <TypeBadge type={e.event_type} /> <StatusBadge status={e.status} /></span>}
        subtitle={`${fmtDate(e.start_time)} · ${fmtTime(e.start_time)} → ${fmtTime(e.end_time)}`}>
        <Link to="/events" className="btn ghost">← Events</Link>
      </PageHead>

      <div className="row" style={{ marginBottom: 16 }}>
        <Btn icon="play" onClick={play} disabled={!e.video_url}>Play video</Btn>
        <a className={`btn ${e.video_url ? "" : "disabled"}`} href={e.video_url ? eventApi.downloadUrl(e.id) : undefined} aria-disabled={!e.video_url}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M12 3v12m0 0l-5-5m5 5l5-5M4 21h16" /></svg>Download video</a>
        <Btn icon="report" className="primary" busy={busy === "report"} disabled={processing} onClick={genReport}>Generate PDF report</Btn>
        <Btn icon="send" busy={busy === "notify"} disabled={processing} onClick={notify}>Send notification</Btn>
        <Btn icon="sparkle" busy={busy === "summary"} disabled={processing} onClick={summarize}>Regenerate summary</Btn>
        <div style={{ flex: 1 }} />
        <Switch checked={e.is_protected} onChange={protect} label="Protect from auto-delete" disabled={busy === "protect"} />
        <Btn icon="trash" className="danger" busy={busy === "delete"} disabled={processing} onClick={remove}>Delete</Btn>
      </div>

      <div className="grid g-live">
        <div className="stack">
          <Panel title="Event video" actions={<span className="muted mono">{fmtDuration(meta.video_duration)} · {fmtBytes(e.video_size_bytes)}</span>}>
            {e.video_url ? (
              <div className="feed"><video ref={videoRef} src={mediaUrl(e.video_url)} controls preload="metadata" poster={mediaUrl(e.snapshot_url)} /></div>
            ) : <Empty title={processing ? "Recording in progress…" : "Video not available"}>{processing && "The clip is finalised a few seconds after the post-event window ends."}</Empty>}
            {meta.video_duration ? (
              <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
                One continuous clip: <b className="mono">{fmtDuration(meta.pre_event_seconds)}</b> pre-event buffer + event + <b className="mono">{fmtDuration(meta.post_event_seconds)}</b> post-event · {meta.video_frames} frames @ {meta.fps} fps · ended: {meta.end_reason}
              </div>
            ) : null}
          </Panel>
          <Panel title={<span className="row">AI summary {e.summary_source === "gemini" && <Badge tone="cyan">Gemini</Badge>}</span>}>
            <AiSummary event={e} />
          </Panel>
          <Panel title="Detection timeline">
            {meta.triggers?.length ? (
              <ul className="timeline">
                {meta.triggers.map((t, i) => (
                  <li key={i}>
                    <span className="t">+{Number(t.t).toFixed(1)}s</span>
                    <span className={`pin ${typeTone(t.type)}`} />
                    <div><TypeBadge type={t.type} /> <span style={{ marginLeft: 6 }}>{cap(t.object) || "motion"}{t.track_id ? <span className="mono muted"> #{t.track_id}</span> : null}{t.zone ? ` in ${t.zone}` : ""}{t.dwell ? <span className="muted"> · dwell {t.dwell}s</span> : null}</span></div>
                  </li>
                ))}
              </ul>
            ) : <Empty title="No trigger data yet" />}
          </Panel>
        </div>

        <div className="stack">
          <Panel title="Snapshot">
            {e.snapshot_url ? <a href={mediaUrl(e.snapshot_url)} target="_blank" rel="noreferrer"><img src={mediaUrl(e.snapshot_url)} alt="Event snapshot" style={{ width: "100%", borderRadius: 8, display: "block" }} /></a> : <Empty title="No snapshot" />}
          </Panel>
          <Panel title="Details">
            <dl className="kv">
              {e.source === "video" && <>
                <dt>Source video</dt><dd><Link to={`/video-analysis/${e.analysis_id}`}>{e.analysis_name || `Analysis #${e.analysis_id}`}</Link></dd>
                <dt>Analysis ID</dt><dd className="mono">#{e.analysis_id ?? "—"}</dd>
                <dt>Video time</dt><dd className="mono">{fmtClock(meta.video_event_start ?? e.video_offset)} – {fmtClock(meta.video_event_end)}</dd>
              </>}
              <dt>Date</dt><dd>{fmtDate(e.start_time)}</dd>
              <dt>Time</dt><dd className="mono">{fmtTime(e.start_time)} – {fmtTime(e.end_time)}</dd>
              <dt>Duration</dt><dd className="mono">{fmtDuration(e.duration)}{meta.loitering_dwell ? ` (dwell ${meta.loitering_dwell}s)` : ""}</dd>
              <dt>Object</dt><dd>{cap(e.object_class) || "—"}</dd>
              <dt>Confidence</dt><dd className="mono">{pct(e.confidence)}</dd>
              <dt>Zone</dt><dd>{e.zone_name || "—"}</dd>
              <dt>Event type</dt><dd><TypeBadge type={e.event_type} /></dd>
              <dt>Notifications</dt><dd><StatusBadge status={e.notification_status} /></dd>
              <dt>Video file</dt><dd className="mono" style={{ fontSize: 12, wordBreak: "break-all" }}>{e.video_path || "—"}</dd>
            </dl>
          </Panel>
          <Panel title="Tracked objects" pad={false}>
            {e.objects.length ? (
              <table className="table">
                <thead><tr><th>Track</th><th>Object</th><th>Max conf.</th><th>Visible</th><th>Zones</th></tr></thead>
                <tbody>{e.objects.map((o) => (
                  <tr key={o.track_id}><td className="mono">#{o.track_id}</td><td>{cap(o.object_class)}</td><td className="mono">{pct(o.max_confidence)}</td>
                    <td className="mono">{fmtDuration((new Date(o.last_seen) - new Date(o.first_seen)) / 1000)}</td><td>{o.zones.join(", ") || "—"}</td></tr>
                ))}</tbody>
              </table>
            ) : <Empty title="No tracked objects" />}
          </Panel>
          <Panel title="Alerts & reports" pad={false}>
            <table className="table"><tbody>
              {e.notifications.map((n) => (
                <tr key={`n${n.id}`}><td>{cap(n.channel)}</td><td><StatusBadge status={n.status} /></td><td className="muted" style={{ fontSize: 12 }}>{n.detail || fmtDateTime(n.created_at)}</td></tr>
              ))}
              {reports.data.map((r) => (
                <tr key={`r${r.id}`}><td>PDF report #{r.id}</td><td className="muted mono">{fmtBytes(r.size_bytes)}</td><td><a href={reportApi.downloadUrl(r.id, true)} target="_blank" rel="noreferrer">Open</a> · <a href={reportApi.downloadUrl(r.id)}>Download</a></td></tr>
              ))}
              {!e.notifications.length && !reports.data.length && <tr><td className="muted">No alerts or reports yet.</td></tr>}
            </tbody></table>
          </Panel>
        </div>
      </div>
    </>
  );
}
