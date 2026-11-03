import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { cameraApi, webcamWsUrl } from "../services/api";
import { useLive } from "./LiveContext";

const WebcamContext = createContext(null);

// Frames sent to the backend: 640x480 (4:3, the pipeline's processing size), centre-cropped like
// the <video> preview (object-fit: cover) so the server's coordinates line up with what you see.
export const FRAME_W = 640;
export const FRAME_H = 480;
const MAX_FPS = 15;
const JPEG_QUALITY = 0.8;
const RESULT_TIMEOUT_MS = 3000;

export const WEBCAM_ERRORS = {
  NotAllowedError: "Camera permission denied. Please allow camera access in your browser settings.",
  SecurityError: "Camera permission denied. Please allow camera access in your browser settings.",
  NotFoundError: "No webcam detected.",
  OverconstrainedError: "No webcam detected.",
  NotReadableError: "The webcam is in use by another application. Close it and press Restart.",
  AbortError: "The webcam could not be started. Press Restart to try again.",
};

function webcamError(e) {
  if (!navigator.mediaDevices?.getUserMedia) {
    return "This browser cannot access the webcam here. Open PreVuCam at http://localhost:5173 (camera access needs localhost or HTTPS).";
  }
  return WEBCAM_ERRORS[e?.name] || `Webcam error: ${e?.message || e}`;
}

/** Draw the current video frame into the canvas, centre-cropped to 4:3 (same crop as object-fit: cover). */
function drawCover(ctx, video) {
  const vw = video.videoWidth, vh = video.videoHeight;
  const target = FRAME_W / FRAME_H;
  let sx = 0, sy = 0, sw = vw, sh = vh;
  if (vw / vh > target) { sw = vh * target; sx = (vw - sw) / 2; } else { sh = vw / target; sy = (vh - sh) / 2; }
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, FRAME_W, FRAME_H);
}

/**
 * Real webcam via navigator.mediaDevices.getUserMedia. Frames are streamed to the backend over
 * /ws/webcam where the shared detection engine (motion → YOLO → tracking → zones → loitering →
 * events) processes them; each reply carries that frame's real tracks, motion state and FPS.
 * Lives at app level so monitoring continues while you switch pages.
 */
export function WebcamProvider({ children }) {
  const { refreshCamera, toast } = useLive();
  const [state, setState] = useState("idle"); // idle | requesting | starting | streaming | error
  const [error, setError] = useState(null);
  const [stream, setStream] = useState(null);
  const [label, setLabel] = useState("");
  const [result, setResult] = useState(null);
  const [clientFps, setClientFps] = useState(0);
  const refs = useRef({ ws: null, video: null, canvas: null, loop: false, stream: null, pending: null, gen: 0 });

  const cleanup = useCallback(() => {
    const r = refs.current;
    r.loop = false;
    r.gen += 1;
    if (r.pending) { clearTimeout(r.pending.timer); r.pending.resolve(null); r.pending = null; }
    if (r.ws) { r.ws.onclose = null; try { r.ws.close(); } catch { /* already closed */ } r.ws = null; }
    if (r.stream) { r.stream.getTracks().forEach((t) => t.stop()); r.stream = null; }
    if (r.video) { r.video.srcObject = null; }
    setStream(null);
    setResult(null);
    setClientFps(0);
  }, []);

  const fail = useCallback(async (message) => {
    cleanup();
    setError(message);
    setState("error");
    try { await cameraApi.stop(); } catch { /* backend may be down */ }
    refreshCamera();
  }, [cleanup, refreshCamera]);

  const sendLoop = useCallback(async (gen) => {
    const r = refs.current;
    const ctx = r.canvas.getContext("2d");
    let frames = 0, windowStart = performance.now();
    while (r.loop && r.gen === gen) {
      const t0 = performance.now();
      if (r.video.readyState >= 2 && r.ws?.readyState === WebSocket.OPEN) {
        drawCover(ctx, r.video);
        const blob = await new Promise((res) => r.canvas.toBlob(res, "image/jpeg", JPEG_QUALITY));
        if (!blob || !r.loop || r.gen !== gen) break;
        const reply = new Promise((resolve) => {
          r.pending = { resolve, timer: setTimeout(() => resolve(null), RESULT_TIMEOUT_MS) };
        });
        const buf = await blob.arrayBuffer();
        if (!r.loop || r.gen !== gen || r.ws?.readyState !== WebSocket.OPEN) break; // stopped meanwhile
        r.ws.send(buf);
        const msg = await reply; // wait for the pipeline before sending the next frame (no backlog)
        if (msg) {
          setResult(msg);
          frames += 1;
        }
        const now = performance.now();
        if (now - windowStart >= 1000) {
          setClientFps(Math.round((frames * 10000) / (now - windowStart)) / 10);
          frames = 0;
          windowStart = now;
        }
      }
      const wait = 1000 / MAX_FPS - (performance.now() - t0);
      await new Promise((res) => setTimeout(res, Math.max(0, wait)));
    }
  }, []);

  const start = useCallback(async () => {
    const r = refs.current;
    cleanup();
    setError(null);
    setState("requesting");
    let media;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("unsupported");
      media = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }, audio: false,
      });
    } catch (e) {
      setError(webcamError(e));
      setState("error");
      return false;
    }
    r.stream = media;
    const track = media.getVideoTracks()[0];
    const devLabel = track?.label || "Webcam";
    setLabel(devLabel);
    track?.addEventListener("ended", () => fail("The webcam was disconnected."));
    if (!r.video) { r.video = document.createElement("video"); r.video.muted = true; r.video.playsInline = true; }
    if (!r.canvas) { r.canvas = document.createElement("canvas"); r.canvas.width = FRAME_W; r.canvas.height = FRAME_H; }
    r.video.srcObject = media;
    try { await r.video.play(); } catch { /* autoplay of a muted stream is allowed */ }
    setStream(media);
    setState("starting");

    try {
      try { await cameraApi.stop(); } catch { /* nothing running */ }
      await cameraApi.start({ source_type: "browser", source: devLabel });
    } catch (e) {
      await fail(`Could not start monitoring: ${e.message}`);
      return false;
    }
    const gen = r.gen;
    const ws = new WebSocket(webcamWsUrl(devLabel));
    ws.binaryType = "arraybuffer";
    r.ws = ws;
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "result" && r.pending) {
        clearTimeout(r.pending.timer);
        const p = r.pending;
        r.pending = null;
        p.resolve(msg);
      } else if (msg.type === "error") {
        toast(msg.detail, "error");
      }
    };
    ws.onopen = () => {
      if (r.gen !== gen) return;
      setState("streaming");
      r.loop = true;
      sendLoop(gen);
      refreshCamera();
    };
    ws.onclose = () => { if (r.gen === gen) fail("Connection to the PreVuCam backend was lost."); };
    return true;
  }, [cleanup, fail, refreshCamera, sendLoop, toast]);

  const stop = useCallback(async () => {
    cleanup();
    setState("idle");
    setError(null);
    try { await cameraApi.stop(); } finally { refreshCamera(); }
  }, [cleanup, refreshCamera]);

  const restart = useCallback(async () => {
    await stop();
    return start();
  }, [start, stop]);

  useEffect(() => () => cleanup(), [cleanup]);

  const active = state === "streaming" || state === "starting" || state === "requesting";
  return (
    <WebcamContext.Provider value={{ state, error, stream, label, result, clientFps, active, start, stop, restart }}>
      {children}
    </WebcamContext.Provider>
  );
}

export const useWebcam = () => useContext(WebcamContext);
