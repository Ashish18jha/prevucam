import { Badge, Btn, Empty, Field, PageHead, Panel, Switch } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useAction, useApi } from "../hooks/useApi";
import { useSettings } from "../hooks/useSettings";
import { analyticsApi, backendUrl, settingsApi, systemApi } from "../services/api";
import { fmtBytes } from "../utils/format";

const KEYS = ["max_storage_gb", "retention_days", "auto_delete_enabled"];

export default function SystemSettings() {
  const { toast, connected } = useLive();
  const storage = useApi(analyticsApi.storage, [], { interval: 30000 });
  const health = useApi(systemApi.health, [], { interval: 10000 });
  const { form, set, save, dirty, busy, reload } = useSettings(KEYS);
  const { busy: aBusy, run } = useAction(toast);
  const s = storage.data;

  const cleanup = () => window.confirm("Delete unprotected events older than the retention period (and oldest first while over quota)?") &&
    run("clean", async () => { const r = await analyticsApi.cleanup(); await storage.reload(true); return r; },
      (r) => `Removed ${r.deleted_events} events, freed ${fmtBytes(r.freed_bytes)}`);
  const reset = () => window.confirm("Reset ALL runtime settings to the .env defaults?") &&
    run("reset", async () => { await settingsApi.reset(); await reload(); }, "Settings reset to defaults");

  const app = s ? s.event_bytes + s.snapshot_bytes + s.report_bytes + s.timelapse_bytes : 0;
  return (
    <>
      <PageHead title="System Settings" subtitle="Storage, retention and service health." />
      <div className="grid g-2">
        <Panel title="Storage">
          {!s ? <Empty title="Loading…" /> : (
            <div className="stack">
              <div className="row between"><span className="muted">Disk</span><span className="mono">{fmtBytes(s.used_bytes)} used · {fmtBytes(s.free_bytes)} free of {fmtBytes(s.total_bytes)}</span></div>
              <div className="meter"><div style={{ width: `${(100 * s.used_bytes) / s.total_bytes}%`, background: "var(--muted)" }} /></div>
              <div className="row between"><span className="muted">PreVuCam quota</span><span className="mono">{fmtBytes(app)} / {fmtBytes(s.max_storage_bytes)} ({s.usage_percent}%)</span></div>
              <div className="meter"><div style={{ width: `${Math.min(100, s.usage_percent)}%` }} /></div>
              <dl className="kv" style={{ marginTop: 6 }}>
                <dt>Event videos</dt><dd className="mono">{fmtBytes(s.event_bytes)}</dd>
                <dt>Snapshots</dt><dd className="mono">{fmtBytes(s.snapshot_bytes)}</dd>
                <dt>Reports</dt><dd className="mono">{fmtBytes(s.report_bytes)}</dd>
                <dt>Timelapses</dt><dd className="mono">{fmtBytes(s.timelapse_bytes)}</dd>
              </dl>
            </div>
          )}
        </Panel>
        <Panel title="Retention policy" actions={<Btn icon="check" className="primary sm" busy={busy} disabled={!dirty} onClick={save}>Save</Btn>}>
          {!form ? <Empty title="Loading…" /> : (
            <div className="stack">
              <div className="form-grid">
                <Field label="Maximum storage (GB)"><input type="number" min="0.1" step="0.5" value={form.max_storage_gb} onChange={(e) => set("max_storage_gb", Number(e.target.value))} /></Field>
                <Field label="Keep events for (days)"><input type="number" min="1" value={form.retention_days} onChange={(e) => set("retention_days", Number(e.target.value))} /></Field>
              </div>
              <Switch checked={form.auto_delete_enabled} onChange={(v) => set("auto_delete_enabled", v)} label="Automatically delete old events (hourly)" />
              <div className="note">Events marked <b>protected</b> on their detail page are never deleted automatically.</div>
              <div><Btn icon="trash" className="danger" busy={aBusy === "clean"} onClick={cleanup}>Run cleanup now</Btn></div>
            </div>
          )}
        </Panel>
        <Panel title="Service health">
          <dl className="kv">
            <dt>API</dt><dd>{health.data ? <Badge tone="green" dot>online · v{health.data.version}</Badge> : <Badge tone="red" dot>offline</Badge>}</dd>
            <dt>Live link</dt><dd>{connected ? <Badge tone="green" dot>WebSocket connected</Badge> : <Badge tone="amber" dot>disconnected</Badge>}</dd>
            <dt>Detector</dt><dd>{health.data?.detector_available ? "YOLOv8 loaded" : "not loaded"}</dd>
            <dt>Camera</dt><dd>{health.data?.camera_running ? "running" : "stopped"}</dd>
          </dl>
        </Panel>
        <Panel title="Maintenance">
          <div className="stack">
            <div className="row">
              <a className="btn" href={backendUrl("/docs")} target="_blank" rel="noreferrer">API docs (Swagger)</a>
              <a className="btn" href={backendUrl("/redoc")} target="_blank" rel="noreferrer">ReDoc</a>
            </div>
            <div><Btn icon="restart" className="danger" busy={aBusy === "reset"} onClick={reset}>Reset all settings to defaults</Btn></div>
          </div>
        </Panel>
      </div>
    </>
  );
}
