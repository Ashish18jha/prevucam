import { Link } from "react-router-dom";
import { ChartCard } from "../components/Charts";
import EventTable from "../components/EventTable";
import LiveFeed from "../components/LiveFeed";
import { Btn, Empty, ErrorBox, PageHead, Panel, Stat, TypeBadge } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useWebcam } from "../context/WebcamContext";
import { useAction, useApi } from "../hooks/useApi";
import { analyticsApi, cameraApi } from "../services/api";
import { fmtBytes, fmtTime, typeTone } from "../utils/format";

export default function Dashboard() {
  const { camera, refreshCamera, feed, toast, eventTick } = useLive();
  const summary = useApi(analyticsApi.summary, [eventTick], { interval: 15000 });
  const charts = useApi(() => analyticsApi.charts(7), [eventTick], { interval: 60000 });
  const { busy, run } = useAction(toast);
  const s = summary.data;
  const c = charts.data;
  const st = s?.storage;

  const webcam = useWebcam();
  const toggleCamera = () => run("cam", async () => {
    if (webcam.active) await webcam.stop();
    else if (camera?.running) await cameraApi.stop();
    else await webcam.start(); // this computer's real webcam (same as Live Monitoring → Start)
    await refreshCamera();
  }, camera?.running ? "Camera stopped" : "Camera started");

  return (
    <>
      <PageHead title="Dashboard" subtitle="Situation overview across the last 7 days.">
        <Btn icon={camera?.running ? "stop" : "play"} className={camera?.running ? "danger" : "primary"} busy={busy === "cam"} onClick={toggleCamera}>
          {camera?.running ? "Stop camera" : "Start camera"}
        </Btn>
      </PageHead>
      <ErrorBox error={summary.error} />

      <div className="grid g-4" style={{ marginBottom: 16 }}>
        <Stat label="Events today" value={s?.events_today} hint={`${s?.events_week ?? "—"} this week · ${s?.events_total ?? "—"} total`} />
        <Stat label="Person detections" value={s?.person_detections} hint={`${s?.vehicle_detections ?? "—"} vehicle events`} accent="var(--green)" />
        <Stat label="Zone violations" value={s?.zone_violations} hint="Relevant objects inside trigger zones" accent="var(--amber)" />
        <Stat label="Loitering events" value={s?.loitering_events} hint={`Avg event ${s?.avg_duration ?? "—"}s`} accent="var(--red)" />
      </div>

      <div className="grid g-live" style={{ marginBottom: 16 }}>
        <Panel title="Live camera" actions={<Link className="btn sm ghost" to="/live">Open monitor →</Link>}>
          <LiveFeed />
        </Panel>
        <div className="stack">
          <Panel title="Live event feed">
            {feed.length === 0 ? (
              <Empty title="Waiting for events">Events will stream in here in real time.</Empty>
            ) : (
              <ul className="timeline">
                {feed.slice(0, 7).map((f, i) => (
                  <li key={i}>
                    <span className="t">{fmtTime(f.at)}</span>
                    <span className={`pin ${typeTone(f.event_type)}`} />
                    <div>
                      <div className="row" style={{ gap: 6 }}>
                        <Link to={`/events/${f.event_id}`} className="mono">#{f.event_id}</Link>
                        <TypeBadge type={f.event_type} />
                        <span className="muted" style={{ fontSize: 12 }}>{f.kind.replace("event_", "")}</span>
                      </div>
                      <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>
                        {f.summary || `${f.object_class || "motion"}${f.zone_name ? ` @ ${f.zone_name}` : ""}`}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <Panel title="Storage">
            {st ? (
              <div className="stack">
                <div className="row between"><span className="muted">PreVuCam data</span><span className="mono">{fmtBytes(st.event_bytes + st.snapshot_bytes + st.report_bytes + st.timelapse_bytes)} / {fmtBytes(st.max_storage_bytes)}</span></div>
                <div className="meter"><div style={{ width: `${Math.min(100, st.usage_percent)}%`, background: st.usage_percent > 85 ? "var(--red)" : "var(--cyan)" }} /></div>
                <div className="row between"><span className="muted">Disk free</span><span className="mono">{fmtBytes(st.free_bytes)} of {fmtBytes(st.total_bytes)}</span></div>
                <div className="row between"><span className="muted">Retention</span><span>{st.auto_delete_enabled ? `${st.retention_days} days (auto)` : "Manual"}</span></div>
              </div>
            ) : <Empty title="—" />}
          </Panel>
        </div>
      </div>

      <div className="grid g-2" style={{ marginBottom: 16 }}>
        <ChartCard title="Events by hour" data={c?.by_hour} />
        <ChartCard title="Events per day" data={c?.by_day?.map((d) => ({ ...d, label: d.label.slice(5) }))} color="#a78bfa" />
      </div>
      <div className="grid g-3" style={{ marginBottom: 16 }}>
        <ChartCard title="Events by object" data={c?.by_object} horizontal height={190} />
        <ChartCard title="Events by type" data={c?.by_type?.map((d) => ({ ...d, label: d.label.replace("_", " ") }))} horizontal height={190} />
        <ChartCard title="Events by zone" data={c?.by_zone} horizontal height={190} />
      </div>
      <Panel title="Recent events" pad={false} actions={<Link className="btn sm ghost" to="/events">All events →</Link>}>
        {s?.recent_events?.length ? <EventTable events={s.recent_events.slice(0, 6)} /> : <Empty title="No events recorded yet">Start the camera to begin monitoring.</Empty>}
      </Panel>
    </>
  );
}
