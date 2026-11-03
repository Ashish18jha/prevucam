import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { cameraApi, wsUrl } from "../services/api";
import { typeLabel } from "../utils/format";

const LiveContext = createContext(null);

/**
 * WebSocket is used only for push updates (camera status, detections, event lifecycle).
 * Everything else goes through REST. If the socket drops we fall back to polling status.
 */
export function LiveProvider({ children }) {
  const [camera, setCamera] = useState(null);
  const [detections, setDetections] = useState({ tracks: [], active_event_id: null });
  const [feed, setFeed] = useState([]);
  const [connected, setConnected] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [eventTick, setEventTick] = useState(0);
  const wsRef = useRef(null);

  const toast = useCallback((message, tone = "info") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t.slice(-3), { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);

  const refreshCamera = useCallback(async () => {
    try { setCamera(await cameraApi.status()); } catch { /* backend offline – status shows it */ setCamera(null); }
  }, []);

  useEffect(() => {
    let stop = false;
    let retry;
    const connect = () => {
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!stop) retry = setTimeout(connect, 3000);
      };
      ws.onmessage = (msg) => {
        const { type, data } = JSON.parse(msg.data);
        if (type === "camera_status") setCamera((c) => ({ ...(c || {}), ...data }));
        else if (type === "detections") setDetections(data);
        else if (type === "analysis_status" && ["completed", "failed", "cancelled"].includes(data.status)) {
          setEventTick((t) => t + 1);
          toast(`Video analysis #${data.analysis_id} ${data.status}${data.status === "completed" ? ` – ${data.events_detected} event(s)` : ""}`,
            data.status === "completed" ? "ok" : data.status === "failed" ? "error" : "info");
        }
        else if (type === "event_started" || type === "event_completed" || type === "event_updated") {
          setFeed((f) => [{ ...data, kind: type, at: new Date().toISOString() }, ...f].slice(0, 30));
          setEventTick((t) => t + 1);
          if (type === "event_started") {
            toast(`Event #${data.event_id}: ${typeLabel(data.event_type)} – ${data.object_class || "motion"}${data.zone_name ? ` @ ${data.zone_name}` : ""}`, "alert");
          }
        }
      };
    };
    connect();
    refreshCamera();
    const poll = setInterval(refreshCamera, 5000);
    return () => { stop = true; clearTimeout(retry); clearInterval(poll); wsRef.current?.close(); };
  }, [refreshCamera, toast]);

  return (
    <LiveContext.Provider value={{ camera, refreshCamera, setCamera, detections, feed, connected, toast, toasts, eventTick }}>
      {children}
    </LiveContext.Provider>
  );
}

export const useLive = () => useContext(LiveContext);
