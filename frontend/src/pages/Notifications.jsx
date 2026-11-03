import { Link } from "react-router-dom";
import { Badge, Btn, Empty, PageHead, Panel, StatusBadge, Switch } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useAction, useApi } from "../hooks/useApi";
import { useSettings } from "../hooks/useSettings";
import { notificationApi } from "../services/api";
import { cap, fmtDateTime, typeLabel } from "../utils/format";

const KEYS = ["twilio_enabled", "telegram_enabled", "email_enabled", "gemini_enabled", "notify_event_types"];

function Channel({ title, configured, enabled, onToggle, envs, where = "backend .env", children }) {
  return (
    <Panel title={title} actions={configured ? <Badge tone="green" dot>Configured</Badge> : <Badge tone="amber" dot>Not configured</Badge>}>
      <div className="stack">
        <Switch checked={enabled} onChange={onToggle} label="Enabled" />
        {!configured && <div className="note">Set <span className="mono">{envs}</span> in <span className="mono">{where}</span> and restart the backend. Secrets are never stored in the database or sent to the browser.</div>}
        {children}
      </div>
    </Panel>
  );
}

export default function Notifications() {
  const { toast } = useLive();
  const status = useApi(notificationApi.status, []);
  const history = useApi(() => notificationApi.history({ limit: 50 }), [], { initial: [] });
  const { form, set, save, dirty, busy } = useSettings(KEYS);
  const { busy: tBusy, run } = useAction(toast);
  const st = status.data;
  if (!st || !form) return <Empty title="Loading…" />;

  const test = (channel) => run(channel, async () => {
    const r = await notificationApi.test(channel);
    await history.reload(true);
    return r;
  }, (r) => r.map((x) => `${cap(x.channel)}: ${x.status}${x.detail ? ` – ${x.detail}` : ""}`).join(" · "));
  const types = ["object_detection", "zone_violation", "loitering", "motion"];

  return (
    <>
      <PageHead title="Notifications & AI" subtitle="Alert channels are independent – one failing never blocks the others or the recording.">
        <Btn icon="check" className="primary" busy={busy} disabled={!dirty} onClick={save}>Save changes</Btn>
      </PageHead>
      <div className="grid g-2" style={{ marginBottom: 16 }}>
        <Channel title="Twilio (SMS / WhatsApp)" configured={st.twilio_configured} enabled={form.twilio_enabled} onToggle={(v) => set("twilio_enabled", v)}
          envs="TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, TWILIO_TO_NUMBER" where="backend/config/api_keys.py">
          {st.twilio_to && <div className="muted">Recipient: <span className="mono">{st.twilio_to}</span></div>}
          <div className="muted" style={{ fontSize: 12.5 }}>One message per finalised event: type, object, zone, confidence, time, duration and the Gemini summary.</div>
          <Btn icon="send" busy={tBusy === "twilio"} disabled={!st.twilio_configured} onClick={() => test("twilio")}>Send test message</Btn>
        </Channel>
        <Channel title="Gemini summaries" configured={st.gemini_configured} enabled={form.gemini_enabled} onToggle={(v) => set("gemini_enabled", v)} envs="GEMINI_API_KEY" where="backend/config/api_keys.py">
          <div className="muted">Model: <span className="mono">{st.gemini_model}</span>. Only finished events (metadata + one snapshot) are sent – never the live stream. Without Gemini, a deterministic template summary is used.</div>
        </Channel>
      </div>
      <h3 style={{ margin: "4px 0 10px" }}>Other channels (optional)</h3>
      <div className="grid g-2" style={{ marginBottom: 16 }}>
        <Channel title="Telegram" configured={st.telegram_configured} enabled={form.telegram_enabled} onToggle={(v) => set("telegram_enabled", v)} envs="TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID">
          <Btn icon="send" busy={tBusy === "telegram"} disabled={!st.telegram_configured} onClick={() => test("telegram")}>Send test message</Btn>
        </Channel>
        <Channel title="Email (SMTP)" configured={st.email_configured} enabled={form.email_enabled} onToggle={(v) => set("email_enabled", v)} envs="SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, ALERT_EMAIL">
          {st.alert_email && <div className="muted">Recipient: <span className="mono">{st.alert_email}</span></div>}
          <Btn icon="send" busy={tBusy === "email"} disabled={!st.email_configured} onClick={() => test("email")}>Send test email</Btn>
        </Channel>
      </div>
      <div className="grid g-2">
        <Panel title="Alert on event types">
          <div className="chip-list">
            {types.map((t) => (
              <button key={t} type="button" className={`chip ${form.notify_event_types.includes(t) ? "on" : ""}`}
                onClick={() => set("notify_event_types", form.notify_event_types.includes(t) ? form.notify_event_types.filter((x) => x !== t) : [...form.notify_event_types, t])}>
                {typeLabel(t)}
              </button>
            ))}
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>Alerts include event type, object, time, zone, the snapshot and the AI summary. You can also re-send any event from its detail page.</p>
        </Panel>
        <Panel title="Delivery history" pad={false} actions={<Btn className="sm ghost" icon="restart" onClick={() => history.reload()}>Refresh</Btn>}>
          {!history.data.length ? <Empty title="No notifications sent yet" /> : (
            <div className="table-wrap" style={{ maxHeight: 360 }}>
              <table className="table">
                <thead><tr><th>Time</th><th>Channel</th><th>Event</th><th>Status</th><th>Detail</th></tr></thead>
                <tbody>{history.data.map((n) => (
                  <tr key={n.id}>
                    <td className="mono" style={{ whiteSpace: "nowrap" }}>{fmtDateTime(n.created_at)}</td>
                    <td>{cap(n.channel)}</td>
                    <td>{n.event_id ? <Link to={`/events/${n.event_id}`} className="mono">#{n.event_id}</Link> : <span className="muted">test</span>}</td>
                    <td><StatusBadge status={n.status} /></td>
                    <td className="muted" style={{ fontSize: 12 }}>{n.detail || "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
