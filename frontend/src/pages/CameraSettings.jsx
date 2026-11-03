import { useEffect, useRef, useState } from "react";
import { Badge, Btn, Empty, Field, PageHead, Panel, Switch } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useWebcam } from "../context/WebcamContext";
import { useAction, useApi } from "../hooks/useApi";
import { cameraApi } from "../services/api";
import { fmtBytes, fmtDateTime } from "../utils/format";

const SOURCES = {
  browser: { label: "This computer's webcam (browser)", placeholder: "", hint: "Uses the webcam of the computer you are viewing PreVuCam on. The browser asks for camera permission; frames are analysed by the backend." },
  webcam: { label: "Webcam (USB / built-in)", placeholder: "0", hint: "Device index, usually 0." },
  rtsp: { label: "RTSP / IP camera", placeholder: "rtsp://user:pass@192.168.1.20:554/stream1", hint: "Any URL OpenCV/FFmpeg can open (rtsp://, http:// MJPEG)." },
  file: { label: "Video file (test mode)", placeholder: "sample_walkin.mp4", hint: "An uploaded file name or an absolute path on the server." },
  picamera: { label: "Raspberry Pi camera", placeholder: "", hint: "CSI camera via picamera2 – Raspberry Pi only." },
};

export default function CameraSettings() {
  const { camera, refreshCamera, toast } = useLive();
  const uploads = useApi(cameraApi.uploads, [], { initial: [] });
  const { busy, run } = useAction(toast);
  const [src, setSrc] = useState({ source_type: "browser", source: "", loop: true });
  const webcam = useWebcam();
  const [progress, setProgress] = useState(null);
  const fileRef = useRef(null);

  useEffect(() => {
    if (camera && !camera.running) setSrc((s) => ({ ...s, source_type: camera.source_type, source: camera.source }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera?.source_type]);

  const start = (body = src) => run("start", async () => {
    if (body.source_type === "browser") { await webcam.start(); return; }
    if (webcam.active) await webcam.stop();
    if (camera?.running) await cameraApi.stop();
    await cameraApi.start({ ...body, source: body.source || (body.source_type === "webcam" ? "0" : "") });
    await refreshCamera();
  }, `Camera started (${body.source_type})`);
  const stop = () => run("stop", async () => { if (webcam.active) await webcam.stop(); else await cameraApi.stop(); await refreshCamera(); }, "Camera stopped");

  const onUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    run("upload", async () => {
      const r = await cameraApi.upload(file, setProgress);
      setProgress(null);
      await uploads.reload(true);
      setSrc({ source_type: "file", source: r.filename, loop: src.loop });
      return r;
    }, (r) => `Uploaded ${r.filename} (${r.frames} frames)`).finally(() => { setProgress(null); e.target.value = ""; });
  };

  const meta = SOURCES[src.source_type];
  return (
    <>
      <PageHead title="Camera Settings" subtitle="Choose the video source: this computer's webcam, a USB/IP/Raspberry Pi camera, or a test video file." />
      <div className="grid g-2">
        <Panel title="Video source">
          <div className="stack">
            <Field label="Source type">
              <select value={src.source_type} onChange={(e) => setSrc({ ...src, source_type: e.target.value, source: "" })}>
                {Object.entries(SOURCES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </Field>
            {meta.placeholder !== "" || src.source_type === "file" ? (
              <Field label="Source" hint={meta.hint}><input value={src.source} placeholder={meta.placeholder} onChange={(e) => setSrc({ ...src, source: e.target.value })} /></Field>
            ) : <div className="note">{meta.hint}</div>}
            {src.source_type === "file" && <Switch checked={src.loop} onChange={(v) => setSrc({ ...src, loop: v })} label="Loop video" />}
            <div className="row">
              <Btn icon="play" className="primary" busy={busy === "start"} onClick={() => start()} disabled={src.source_type === "file" && !src.source}>{camera?.running ? "Switch source" : "Start camera"}</Btn>
              <Btn icon="stop" className="danger" busy={busy === "stop"} onClick={stop} disabled={!camera?.running}>Stop</Btn>
              <Btn icon="restart" busy={busy === "restart"} onClick={() => run("restart", async () => { if (webcam.active) await webcam.restart(); else await cameraApi.restart(); await refreshCamera(); }, "Camera restarted")} disabled={!camera?.running}>Restart</Btn>
            </div>
            {webcam.error && <div className="error-box">{webcam.error}</div>}
          </div>
        </Panel>
        <Panel title="Status">
          {!camera ? <Empty title="Backend unreachable" /> : (
            <dl className="kv">
              <dt>State</dt><dd>{camera.running ? (camera.connected ? <Badge tone="green" dot pulse>Streaming</Badge> : <Badge tone="amber" dot>Reconnecting</Badge>) : <Badge dot>Stopped</Badge>}</dd>
              <dt>Source</dt><dd className="mono" style={{ wordBreak: "break-all" }}>{camera.source_type}: {camera.source}</dd>
              <dt>Resolution</dt><dd className="mono">{camera.resolution?.join(" × ")}</dd>
              <dt>Frame rate</dt><dd className="mono">{camera.fps} fps</dd>
              <dt>Frames</dt><dd className="mono">{camera.frames_processed}</dd>
              <dt>Last frame</dt><dd className="mono">{fmtDateTime(camera.last_frame_at)}</dd>
              <dt>Error</dt><dd style={{ color: camera.error ? "var(--red)" : undefined }}>{camera.error || "—"}</dd>
            </dl>
          )}
        </Panel>
        <Panel title="Test videos" actions={
          <>
            <input ref={fileRef} type="file" accept="video/*" hidden onChange={onUpload} />
            <Btn icon="upload" className="sm" busy={busy === "upload"} onClick={() => fileRef.current?.click()}>{progress != null ? `Uploading ${progress}%` : "Upload video"}</Btn>
          </>
        } pad={false}>
          {!uploads.data.length ? <Empty title="No uploaded videos">Upload an MP4, or generate one with <span className="mono">python scripts/make_sample_video.py</span>.</Empty> : (
            <table className="table">
              <thead><tr><th>File</th><th>Length</th><th>Size</th><th /></tr></thead>
              <tbody>{uploads.data.map((u) => (
                <tr key={u.filename}>
                  <td className="mono" style={{ wordBreak: "break-all" }}>{u.filename}<div className="faint" style={{ fontSize: 11.5 }}>{u.width}×{u.height} · {u.fps.toFixed(0)} fps</div></td>
                  <td className="mono">{(u.frames / u.fps).toFixed(1)}s</td>
                  <td className="mono">{fmtBytes(u.size_bytes)}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <Btn className="sm" icon="play" onClick={() => start({ source_type: "file", source: u.filename, loop: src.loop })}>Use</Btn>
                    <Btn className="sm ghost" icon="trash" onClick={() => window.confirm(`Delete ${u.filename}?`) && run("del", async () => { await cameraApi.deleteUpload(u.filename); await uploads.reload(true); }, "Deleted")} />
                  </td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Panel>
        <Panel title="Raspberry Pi deployment">
          <div className="stack muted" style={{ fontSize: 13 }}>
            <div>On a Raspberry Pi, choose <b>Raspberry Pi camera</b> (requires <span className="mono">picamera2</span>, preinstalled on Raspberry Pi OS) or a USB webcam.</div>
            <div>For best performance set <span className="mono">YOLO_IMGSZ=320</span>, <span className="mono">CAMERA_FPS=10</span> and a detection interval of 3–5 frames. The motion gate keeps YOLO idle when nothing moves.</div>
            <div>Defaults are set in <span className="mono">.env</span> (<span className="mono">CAMERA_SOURCE_TYPE</span>, <span className="mono">CAMERA_SOURCE</span>, <span className="mono">CAMERA_AUTOSTART</span>).</div>
          </div>
        </Panel>
      </div>
    </>
  );
}
