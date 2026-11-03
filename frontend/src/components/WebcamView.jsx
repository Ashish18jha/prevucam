import { useEffect, useRef } from "react";
import Icon from "./Icons";
import { Badge } from "./UI";
import { FRAME_H, FRAME_W, useWebcam } from "../context/WebcamContext";

// same colours as the server-side overlay (image_utils.COLORS) and the Live Monitoring legend
const STATE_COLOR = { normal: "#78a0b4", relevant: "#22c55e", zone: "#f59e0b", loitering: "#ef4444" };

/**
 * The user's real webcam (local <video>, no round-trip) with the backend's detections drawn on top:
 * bounding boxes, class, confidence, tracking ID, dwell time and the configured zones.
 */
export default function WebcamView({ zones = [], overlay = true }) {
  const { stream, result, state, error } = useWebcam();
  const videoRef = useRef(null);
  const canvasRef = useRef(null);

  useEffect(() => {
    const v = videoRef.current;
    if (v && v.srcObject !== stream) {
      v.srcObject = stream;
      if (stream) v.play().catch(() => {});
    }
  }, [stream]);

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const { width, height } = c.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    c.width = width * dpr;
    c.height = height * dpr;
    const ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (!overlay || !stream) return;
    const sx = width / FRAME_W, sy = height / FRAME_H;

    for (const z of zones.filter((zz) => zz.active)) {
      ctx.beginPath();
      z.points.forEach(([x, y], i) => (i ? ctx.lineTo(x * width, y * height) : ctx.moveTo(x * width, y * height)));
      ctx.closePath();
      ctx.fillStyle = `${z.color}26`;
      ctx.fill();
      ctx.strokeStyle = z.color;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.font = "600 12px system-ui";
      ctx.fillStyle = z.color;
      ctx.fillText(z.name, z.points[0][0] * width + 4, z.points[0][1] * height + 15);
    }
    for (const t of result?.tracks || []) {
      const [x1, y1, x2, y2] = t.bbox;
      const color = STATE_COLOR[t.state] || STATE_COLOR.normal;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
      const label = `#${t.track_id} ${t.class} ${Math.round(t.confidence * 100)}%${t.dwell ? ` ${Math.round(t.dwell)}s` : ""}`;
      ctx.font = "600 12px system-ui";
      const w = ctx.measureText(label).width + 8;
      const lx = Math.max(0, Math.min(x1 * sx, width - w)); // keep the label inside the frame
      const ly = y1 * sy >= 18 ? y1 * sy - 18 : y1 * sy;
      ctx.fillStyle = color;
      ctx.fillRect(lx, ly, w, 18);
      ctx.fillStyle = "#0b0f14";
      ctx.fillText(label, lx + 4, ly + 13);
    }
  }, [result, zones, overlay, stream]);

  return (
    <div className="feed webcam-feed">
      <video ref={videoRef} muted playsInline autoPlay style={{ objectFit: "cover", visibility: stream ? "visible" : "hidden" }} />
      <canvas ref={canvasRef} className="feed-canvas" />
      {!stream && (
        <div className="feed-off">
          <div style={{ padding: 16 }}>
            <Icon name={state === "error" ? "off" : "camera"} />
            <div style={error ? { color: "var(--red)", maxWidth: 420 } : null}>
              {error || (state === "requesting" ? "Waiting for camera permission…" : "Webcam is off")}
            </div>
            {!error && state === "idle" && <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>Press Start to use this computer's webcam.</div>}
          </div>
        </div>
      )}
      <span className="corner tl" /><span className="corner tr" /><span className="corner bl" /><span className="corner br" />
      {stream && (
        <div className="feed-overlay">
          <Badge tone={result?.motion ? "amber" : "slate"} dot>{result?.motion ? "Motion detected" : "No motion"}</Badge>
          {result?.active_event_id ? <Badge tone="red" dot pulse>REC #{result.active_event_id}</Badge> : null}
        </div>
      )}
    </div>
  );
}
