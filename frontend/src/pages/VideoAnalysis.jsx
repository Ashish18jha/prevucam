import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Icon from "../components/Icons";
import { Badge, Btn, Empty, ErrorBox, PageHead, Panel } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useAction, useApi } from "../hooks/useApi";
import { videoAnalysisApi } from "../services/api";
import { fmtBytes, fmtClock, fmtDateTime } from "../utils/format";

const FORMATS = [".mp4", ".avi", ".mov", ".mkv", ".webm"];
const extOf = (name) => (name.match(/\.[^.]+$/)?.[0] || "").toLowerCase();

/** Duration / resolution read in the browser before upload (only for formats the browser can decode). */
function useLocalMetadata(file) {
  const [meta, setMeta] = useState(null);
  useEffect(() => {
    setMeta(null);
    if (!file) return undefined;
    const url = URL.createObjectURL(file);
    const v = document.createElement("video");
    v.preload = "metadata";
    v.onloadedmetadata = () => setMeta({ duration: v.duration, width: v.videoWidth, height: v.videoHeight });
    v.onerror = () => setMeta({ unreadable: true });
    v.src = url;
    return () => { v.removeAttribute("src"); URL.revokeObjectURL(url); };
  }, [file]);
  return meta;
}

export function StatusPill({ status }) {
  const tone = { uploaded: "slate", queued: "amber", processing: "cyan", completed: "green", failed: "red", cancelled: "slate" }[status];
  return <Badge tone={tone} dot pulse={status === "processing" || status === "queued"}>{status}</Badge>;
}

export default function VideoAnalysis() {
  const { toast } = useLive();
  const nav = useNavigate();
  const inputRef = useRef(null);
  const abortRef = useRef(null);
  const [file, setFile] = useState(null);
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState(null);
  const [uploaded, setUploaded] = useState(null);
  const [error, setError] = useState(null);
  const local = useLocalMetadata(file);
  const { busy, run } = useAction(toast);
  const list = useApi(videoAnalysisApi.list, [], { initial: [], interval: 4000 });

  const pick = (f) => {
    setError(null);
    setUploaded(null);
    setProgress(null);
    if (!f) return;
    if (!FORMATS.includes(extOf(f.name))) {
      setFile(null);
      setError(new Error(`Unsupported format "${extOf(f.name) || f.name}". Supported: ${FORMATS.join(" ")}`));
      return;
    }
    setFile(f);
  };

  const upload = async () => {
    if (!file) return;
    setError(null);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setProgress(0);
    try {
      const r = await videoAnalysisApi.upload(file, setProgress, ctrl.signal);
      setUploaded(r);
      toast(`Uploaded ${r.original_name} – ready to analyse`, "ok");
      list.reload(true);
    } catch (e) {
      setProgress(null);
      if (e.message !== "canceled") setError(e);
    } finally {
      abortRef.current = null;
    }
  };

  const start = () => run("start", async () => {
    await videoAnalysisApi.start(uploaded.analysis_id);
    nav(`/video-analysis/${uploaded.analysis_id}`);
  }, "Analysis started");

  const cancel = () => {
    if (abortRef.current) { abortRef.current.abort(); toast("Upload cancelled", "info"); }
    setFile(null); setUploaded(null); setProgress(null); setError(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const uploading = progress != null && !uploaded && !error;
  const meta = uploaded || (local && !local.unreadable ? local : null);

  return (
    <>
      <PageHead title="Recorded Video Analysis"
        subtitle="Upload a prerecorded surveillance video and analyze it using the PreVuCam AI surveillance pipeline." />
      <div className="grid g-live">
        <div className="stack">
          <Panel title="Upload video">
            <div className={`dropzone ${drag ? "drag" : ""} ${file ? "has-file" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); if (!uploading) pick(e.dataTransfer.files?.[0]); }}
              onClick={() => !uploading && inputRef.current?.click()}
              role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}>
              <input ref={inputRef} type="file" hidden accept={FORMATS.join(",") + ",video/*"} onChange={(e) => pick(e.target.files?.[0])} />
              <Icon name="upload" size={30} />
              <div style={{ fontWeight: 600, marginTop: 8 }}>Drag and drop a video here</div>
              <div className="muted" style={{ fontSize: 12.5, margin: "4px 0 12px" }}>Supported formats: {FORMATS.join("  ")}</div>
              <span className="btn sm" onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }}>Choose Video</span>
            </div>

            {file && (
              <div className="file-card">
                <dl className="kv">
                  <dt>Filename</dt><dd className="mono" style={{ wordBreak: "break-all" }}>{file.name}</dd>
                  <dt>File size</dt><dd className="mono">{fmtBytes(file.size)}</dd>
                  <dt>Duration</dt><dd className="mono">{meta?.duration ? `${fmtClock(meta.duration)} (${meta.duration.toFixed(1)} s)` : uploaded ? "unknown" : local?.unreadable ? "read after upload" : "reading…"}</dd>
                  <dt>Resolution</dt><dd className="mono">{meta?.width ? `${meta.width} × ${meta.height}` : uploaded ? "unknown" : local?.unreadable ? "read after upload" : "reading…"}</dd>
                  {uploaded && <><dt>Frame rate</dt><dd className="mono">{uploaded.fps} fps · {uploaded.total_frames} frames</dd></>}
                  <dt>Status</dt><dd>{uploaded ? <StatusPill status={uploaded.status} /> : uploading ? <Badge tone="cyan" dot pulse>uploading</Badge> : <Badge>selected</Badge>}</dd>
                </dl>
                {progress != null && (
                  <div style={{ marginTop: 12 }}>
                    <div className="row between" style={{ fontSize: 12.5, marginBottom: 6 }}>
                      <span className="muted">{uploaded ? "Upload complete – metadata extracted by the server" : progress >= 100 ? "Validating video on the server…" : "Uploading…"}</span>
                      <span className="mono">{progress}%</span>
                    </div>
                    <div className="meter"><div style={{ width: `${progress}%`, background: uploaded ? "var(--green)" : "var(--cyan)" }} /></div>
                  </div>
                )}
              </div>
            )}
            <div style={{ marginTop: 12 }}><ErrorBox error={error} /></div>
            <div className="row" style={{ marginTop: 14 }}>
              <Btn icon="upload" disabled={!file || uploading || !!uploaded} busy={uploading} onClick={upload}>Upload</Btn>
              <Btn icon="play" className="primary" disabled={!uploaded || uploaded.status !== "uploaded"} busy={busy === "start"} onClick={start}
                title={!uploaded ? "Upload a valid video first" : undefined}>Start Analysis</Btn>
              <Btn icon="x" className="ghost" disabled={!file && !error} onClick={cancel}>Cancel</Btn>
            </div>
          </Panel>
          <Panel title="What happens during analysis">
            <ol className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7, fontSize: 13 }}>
              <li>The video is decoded frame by frame with OpenCV (never loaded into memory at once).</li>
              <li>Motion detection gates YOLOv8; detections are filtered by your <Link to="/detection">relevant objects</Link>.</li>
              <li>Objects are tracked across frames and checked against your <Link to="/zones">zones</Link> and loitering threshold.</li>
              <li>Each event is saved as one clip: 7 s before + the event + 7 s after, with snapshot and metadata.</li>
              <li>Gemini writes the summary (when configured) and alerts are sent once per event.</li>
            </ol>
          </Panel>
        </div>

        <Panel title="Analysed videos" pad={false} actions={<span className="muted mono">{list.data.length}</span>}>
          <ErrorBox error={list.error} />
          {!list.data.length ? <Empty title="No videos yet">Uploaded videos and their results appear here.</Empty> : (
            <table className="table">
              <tbody>
                {list.data.map((a) => (
                  <tr key={a.analysis_id} className="clickable" onClick={() => nav(`/video-analysis/${a.analysis_id}`)}>
                    <td>
                      <div style={{ fontWeight: 600, wordBreak: "break-all" }}>{a.original_name}</div>
                      <div className="faint" style={{ fontSize: 12 }}>#{a.analysis_id} · {fmtClock(a.duration)} · {a.width}×{a.height} · {fmtDateTime(a.created_at)}</div>
                      {a.status === "processing" && <div className="meter" style={{ marginTop: 6, height: 5 }}><div style={{ width: `${a.progress}%` }} /></div>}
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <StatusPill status={a.status} />
                      {a.status === "completed" && <div className="muted mono" style={{ fontSize: 12, marginTop: 4 }}>{a.events_detected} events</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </>
  );
}

