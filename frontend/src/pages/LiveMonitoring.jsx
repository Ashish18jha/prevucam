import { useState } from "react";
import { Link } from "react-router-dom";
import LiveFeed from "../components/LiveFeed";
import WebcamView from "../components/WebcamView";
import { Badge, Btn, Empty, ErrorBox, PageHead, Panel, Switch } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useWebcam } from "../context/WebcamContext";
import { useAction, useApi } from "../hooks/useApi";
import { cameraApi, detectionApi, zoneApi } from "../services/api";
import { cap, fmtDuration, pct } from "../utils/format";

const STATE = {
  normal: { tone: "slate", label: "Ignored" },
  relevant: { tone: "green", label: "Relevant" },
  zone: { tone: "amber", label: "Zone violation" },
  loitering: { tone: "red", label: "Loitering" },
};

export default function LiveMonitoring() {
  const { camera, refreshCamera, detections, toast } = useLive();
  const webcam = useWebcam();
  const [overlay, setOverlay] = useState(true);
  const { busy, run } = useAction(toast);
  const stays = useApi(detectionApi.activeLoitering, [], { interval: 2000, initial: [] });
  const zones = useApi(zoneApi.list, [], { initial: [], interval: 15000 });

  // A server-side source (USB/RTSP/Pi camera, started from the Camera page) is shown via MJPEG;
  // otherwise Live Monitoring uses this computer's webcam through the browser.
  const serverSource = camera?.running && camera.source_type !== "browser";
  const usingWebcam = !serverSource;
  const res = webcam.result;
  const tracks = usingWebcam ? (res?.tracks || []) : (detections?.tracks || []);
  const running = usingWebcam ? webcam.active : camera?.running;
  const motion = usingWebcam ? res?.motion : camera?.motion;
  const activeEvent = usingWebcam ? res?.active_event_id : (detections?.active_event_id || camera?.active_event_id);

  const act = (key, fn, msg) => run(key, async () => { await fn(); await refreshCamera(); }, msg);
  const start = () => run("start", async () => { if (await webcam.start()) toast("Webcam monitoring started", "ok"); });
  const stop = () => (usingWebcam ? run("stop", webcam.stop, "Monitoring stopped") : act("stop", cameraApi.stop, "Camera stopped"));
  const restart = () => (usingWebcam ? run("restart", webcam.restart, "Webcam restarted") : act("restart", cameraApi.restart, "Camera restarted"));

  const status = usingWebcam
    ? { streaming: <Badge tone="green" dot pulse>Streaming</Badge>, starting: <Badge tone="amber" dot pulse>Connecting…</Badge>,
        requesting: <Badge tone="amber" dot pulse>Waiting for permission</Badge>, error: <Badge tone="red" dot>Error</Badge>,
        idle: <Badge dot>Stopped</Badge> }[webcam.state]
    : (camera.connected ? <Badge tone="green" dot>Streaming</Badge> : <Badge tone="amber" dot>Connecting</Badge>);

  return (
    <>
      <PageHead title="Live Monitoring" subtitle="Real-time detections, tracking IDs and zone overlays.">
        <Switch checked={overlay} onChange={setOverlay} label="Overlays" />
        {running ? (
          <>
            <Btn icon="restart" busy={busy === "restart"} onClick={restart}>Restart</Btn>
            <Btn icon="stop" className="danger" busy={busy === "stop"} onClick={stop}>Stop</Btn>
          </>
        ) : (
          <>
            {webcam.state === "error" && <Btn icon="restart" busy={busy === "restart"} onClick={restart}>Restart</Btn>}
            <Btn icon="play" className="primary" busy={busy === "start"} onClick={start}>Start</Btn>
          </>
        )}
      </PageHead>
      {usingWebcam && webcam.error && <div style={{ marginBottom: 16 }}><ErrorBox error={webcam.error} /></div>}

      <div className="grid g-live">
        <div className="stack">
          <Panel pad={false}><div style={{ padding: 12 }}>
            {usingWebcam ? <WebcamView zones={zones.data} overlay={overlay} /> : <LiveFeed overlay={overlay} />}
          </div></Panel>
          <div className="row" style={{ gap: 14, fontSize: 12.5 }}>
            {Object.entries(STATE).map(([k, v]) => <Badge key={k} tone={v.tone} dot>{v.label}</Badge>)}
            <span className="muted">Box colours on the feed follow the same legend.</span>
          </div>
        </div>
        <div className="stack">
          <Panel title="Pipeline">
            <dl className="kv">
              <dt>Source</dt><dd className="mono">{usingWebcam ? `Webcam${webcam.label ? ` · ${webcam.label}` : ""}` : `${camera.source_type}: ${camera.source}`}</dd>
              <dt>Status</dt><dd>{status}</dd>
              <dt>Throughput</dt><dd className="mono">{usingWebcam
                ? (webcam.active ? `${res?.fps ?? 0} fps processed · ${webcam.clientFps} fps sent · frame ${res?.frame ?? 0}` : "—")
                : `${camera?.fps ?? 0} fps · ${camera?.frames_processed ?? 0} frames`}</dd>
              <dt>Motion gate</dt><dd>{!running ? <span className="muted">—</span> : motion ? <Badge tone="amber" dot>Detected</Badge>
                : <span className="muted">No motion{tracks.length ? ` – YOLO tracking ${tracks.length} object(s)` : " (YOLO paused)"}</span>}</dd>
              <dt>Detector</dt><dd>{camera?.detector_available || res?.detector_available ? "YOLOv8 ready" : <span style={{ color: "var(--amber)" }}>{camera?.detector_error || "loading…"}</span>}</dd>
              <dt>Active event</dt><dd>{activeEvent ? <Link to={`/events/${activeEvent}`}>#{activeEvent} (recording)</Link> : "None"}</dd>
              {!usingWebcam && camera?.error && <><dt>Last error</dt><dd style={{ color: "var(--red)" }}>{camera.error}</dd></>}
            </dl>
          </Panel>
          <Panel title="Tracked objects" actions={<span className="muted mono">{tracks.length}</span>} pad={false}>
            {tracks.length === 0 ? <Empty title="Nothing tracked">{running ? "Objects appear here once motion triggers detection." : "Start monitoring to track objects."}</Empty> : (
              <table className="table">
                <thead><tr><th>ID</th><th>Object</th><th>Conf.</th><th>State</th><th>Zone</th></tr></thead>
                <tbody>
                  {tracks.map((t) => (
                    <tr key={t.track_id}>
                      <td className="mono">#{t.track_id}</td>
                      <td>{cap(t.class)}</td>
                      <td className="mono">{pct(t.confidence)}</td>
                      <td><Badge tone={STATE[t.state]?.tone}>{STATE[t.state]?.label}</Badge></td>
                      <td>{t.zones?.length ? <><Badge tone="amber">Inside</Badge> {t.zones.join(", ")}</> : <span className="faint">Outside zones</span>}{t.dwell ? <span className="muted mono"> · {fmtDuration(t.dwell)}</span> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
          <Panel title="Zone dwell (loitering watch)" pad={false}>
            {!stays.data?.length ? <Empty title="No one inside a zone" /> : (
              <table className="table">
                <thead><tr><th>Track</th><th>Zone</th><th>Dwell</th><th>Threshold</th></tr></thead>
                <tbody>
                  {stays.data.map((s) => (
                    <tr key={`${s.track_id}-${s.zone_id}`}>
                      <td className="mono">#{s.track_id}</td>
                      <td>{s.zone_name}</td>
                      <td className="mono" style={{ color: s.triggered ? "var(--red)" : undefined }}>{fmtDuration(s.duration)}</td>
                      <td className="mono muted">{s.threshold}s {s.triggered && <Badge tone="red">alert</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}
