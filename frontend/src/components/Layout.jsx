import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import Icon from "./Icons";
import { Badge } from "./UI";
import { useLive } from "../context/LiveContext";

const NAV = [
  ["Monitor", [["/", "dashboard", "Dashboard"], ["/live", "live", "Live Monitoring"], ["/events", "events", "Events"], ["/video-analysis", "scan", "Video Analysis"]]],
  ["Configure", [["/zones", "zones", "Zones"], ["/detection", "detect", "Detection"], ["/camera", "camera", "Camera"], ["/notifications", "bell", "Notifications"]]],
  ["Output", [["/reports", "report", "Reports"], ["/timelapse", "film", "Timelapse"], ["/system", "settings", "System"]]],
];

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(id); }, []);
  return <span className="clock">{now.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short" })} · {now.toLocaleTimeString()}</span>;
}

export function CameraBadge() {
  const { camera } = useLive();
  if (!camera) return <Badge tone="red" dot>API offline</Badge>;
  if (camera.running && camera.source_type === "browser" && !camera.webcam_connected) return <Badge tone="amber" dot pulse>Waiting for webcam…</Badge>;
  if (camera.running && camera.connected) return <Badge tone="green" dot pulse>{camera.source_type === "browser" ? "Webcam live" : "Camera live"} · {camera.fps} fps</Badge>;
  if (camera.running) return <Badge tone="amber" dot pulse>Connecting…</Badge>;
  return <Badge tone="slate" dot>Camera stopped</Badge>;
}

export default function Layout() {
  const { connected, toasts, detections, camera } = useLive();
  const recording = detections?.active_event_id || camera?.active_event_id;
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" />
          <div>
            <div className="brand-name">PREVUCAM</div>
            <div className="brand-sub">Event surveillance</div>
          </div>
        </div>
        {NAV.map(([group, items]) => (
          <div key={group}>
            <div className="nav-group">{group}</div>
            <nav className="nav">
              {items.map(([to, icon, label]) => (
                <NavLink key={to} to={to} end={to === "/"}><Icon name={icon} />{label}</NavLink>
              ))}
            </nav>
          </div>
        ))}
        <div className="sidebar-foot">
          <div className="row"><span className="dot" style={{ color: connected ? "var(--green)" : "var(--red)" }} /><span className="muted">{connected ? "Live link connected" : "Live link offline"}</span></div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <CameraBadge />
          {recording ? <Badge tone="red" dot pulse>REC · event #{recording}</Badge> : null}
          {camera?.detector_available === false && camera?.detector_error && <Badge tone="amber">Detector unavailable</Badge>}
          <div className="spacer" />
          <Clock />
        </header>
        <main className="content"><Outlet /></main>
      </div>
      <div className="toasts">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.tone}`}>{t.message}</div>)}
      </div>
    </div>
  );
}
