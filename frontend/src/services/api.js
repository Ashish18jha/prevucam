import axios from "axios";

const BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const API_KEY = import.meta.env.VITE_API_KEY || "";

export const http = axios.create({
  baseURL: `${BASE}/api`,
  timeout: 30000,
  headers: API_KEY ? { "X-API-Key": API_KEY } : {},
});

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail;
    let message = err.message;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) message = detail.map((d) => `${(d.loc || []).slice(-1)[0] ?? ""}: ${d.msg}`).join("; ");
    const unreachable = !err.response || err.response?.data?.backend_unreachable;
    if (!err.response) message = "Backend unreachable – is the API server running? (cd backend && python run.py)";
    return Promise.reject(Object.assign(new Error(message), { status: err.response?.status, unreachable }));
  }
);

const data = (p) => p.then((r) => r.data);
const keyParam = API_KEY ? `api_key=${encodeURIComponent(API_KEY)}` : "";
const withKey = (url) => (keyParam ? `${url}${url.includes("?") ? "&" : "?"}${keyParam}` : url);

/** URL for files the backend serves under /media (videos, snapshots, timelapses). */
export const mediaUrl = (path) => (path ? withKey(`${BASE}${path}`) : null);
export const backendUrl = (path) => `${BASE}${path}`;
export const apiUrl = (path) => withKey(`${BASE}/api${path}`);
export const streamUrl = (overlay = true, nonce = 0) => apiUrl(`/camera/stream?overlay=${overlay}&n=${nonce}`);
export const webcamWsUrl = (label = "") => {
  const origin = BASE || window.location.origin;
  return withKey(origin.replace(/^http/, "ws") + `/ws/webcam?label=${encodeURIComponent(label.slice(0, 80))}`);
};
export const wsUrl = () => {
  const origin = BASE || window.location.origin;
  return withKey(origin.replace(/^http/, "ws") + "/ws/live");
};

export const cameraApi = {
  status: () => data(http.get("/camera/status")),
  start: (body = {}) => data(http.post("/camera/start", body)),
  stop: () => data(http.post("/camera/stop")),
  restart: () => data(http.post("/camera/restart")),
  uploads: () => data(http.get("/camera/uploads")),
  deleteUpload: (name) => data(http.delete(`/camera/uploads/${encodeURIComponent(name)}`)),
  upload: (file, onProgress) => {
    const form = new FormData();
    form.append("file", file);
    return data(http.post("/camera/upload", form, {
      timeout: 0,
      onUploadProgress: (e) => onProgress?.(e.total ? Math.round((e.loaded / e.total) * 100) : 0),
    }));
  },
  snapshotUrl: (overlay = false) => apiUrl(`/camera/snapshot?overlay=${overlay}&t=${Date.now()}`),
};

export const eventApi = {
  list: (params) => data(http.get("/events", { params })),
  get: (id) => data(http.get(`/events/${id}`)),
  update: (id, body) => data(http.patch(`/events/${id}`, body)),
  remove: (id) => data(http.delete(`/events/${id}`)),
  regenerateSummary: (id) => data(http.post(`/events/${id}/summary`)),
  notify: (id) => data(http.post(`/events/${id}/notify`)),
  downloadUrl: (id) => apiUrl(`/events/${id}/video`),
};

export const zoneApi = {
  list: () => data(http.get("/zones")),
  create: (body) => data(http.post("/zones", body)),
  update: (id, body) => data(http.put(`/zones/${id}`, body)),
  remove: (id) => data(http.delete(`/zones/${id}`)),
};

export const settingsApi = {
  get: () => data(http.get("/settings")),
  update: (body) => data(http.put("/settings", body)),
  reset: () => data(http.post("/settings/reset")),
  relevantObjects: () => data(http.get("/settings/relevant-objects")),
  setRelevantObjects: (relevant_objects) => data(http.put("/settings/relevant-objects", { relevant_objects })),
  loitering: () => data(http.get("/loitering/settings")),
  setLoitering: (body) => data(http.put("/loitering/settings", body)),
};

export const detectionApi = {
  live: () => data(http.get("/detection/live")),
  classes: () => data(http.get("/detection/classes")),
  model: () => data(http.get("/detection/model")),
  reloadModel: () => data(http.post("/detection/model/reload")),
  activeLoitering: () => data(http.get("/loitering/active")),
  loiteringRecords: (params) => data(http.get("/loitering/records", { params })),
};

export const reportApi = {
  generate: (eventId) => data(http.post(`/reports/events/${eventId}`)),
  list: (params) => data(http.get("/reports", { params })),
  remove: (id) => data(http.delete(`/reports/${id}`)),
  downloadUrl: (id, inline = false) => apiUrl(`/reports/${id}${inline ? "?inline=true" : ""}`),
};

export const timelapseApi = {
  generate: (date, speed) => data(http.post("/timelapse/generate", { date, speed })),
  list: () => data(http.get("/timelapse")),
  get: (id) => data(http.get(`/timelapse/${id}`)),
  remove: (id) => data(http.delete(`/timelapse/${id}`)),
  downloadUrl: (id) => apiUrl(`/timelapse/${id}/download`),
};

export const videoAnalysisApi = {
  upload: (file, onProgress, signal) => {
    const form = new FormData();
    form.append("file", file);
    return data(http.post("/video-analysis/upload", form, {
      timeout: 0,
      signal,
      onUploadProgress: (e) => onProgress?.(e.total ? Math.round((e.loaded / e.total) * 100) : 0),
    }));
  },
  list: () => data(http.get("/video-analysis")),
  get: (id) => data(http.get(`/video-analysis/${id}`)),
  status: (id) => data(http.get(`/video-analysis/${id}/status`)),
  start: (id, force = false) => data(http.post(`/video-analysis/${id}/start`, null, { params: force ? { force: true } : {} })),
  cancel: (id) => data(http.post(`/video-analysis/${id}/cancel`)),
  events: (id) => data(http.get(`/video-analysis/${id}/events`)),
  remove: (id, deleteEvents) => data(http.delete(`/video-analysis/${id}`, { params: { delete_events: !!deleteEvents } })),
  videoUrl: (id, previewReady) => apiUrl(`/video-analysis/${id}/video${previewReady ? "?preview=1" : ""}`),
  frameUrl: (id, t) => apiUrl(`/video-analysis/${id}/frame?${t != null ? `t=${t}&` : ""}n=${Date.now()}`),
  originalUrl: (id) => apiUrl(`/video-analysis/${id}/video?original=true`),
};

export const analyticsApi = {
  summary: () => data(http.get("/analytics/summary")),
  charts: (days = 7) => data(http.get("/analytics/charts", { params: { days } })),
  storage: () => data(http.get("/storage")),
  cleanup: () => data(http.post("/storage/cleanup")),
};

export const notificationApi = {
  status: () => data(http.get("/notifications/status")),
  test: (channel) => data(http.post("/notifications/test", { channel })),
  history: (params) => data(http.get("/notifications", { params })),
};

export const systemApi = {
  health: () => data(http.get("/health")),
};
