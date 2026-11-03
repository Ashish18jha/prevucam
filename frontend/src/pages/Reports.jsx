import { useState } from "react";
import { Link } from "react-router-dom";
import { Btn, Empty, ErrorBox, Field, PageHead, Panel } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useAction, useApi } from "../hooks/useApi";
import { eventApi, reportApi } from "../services/api";
import { fmtBytes, fmtDateTime, typeLabel } from "../utils/format";

export default function Reports() {
  const { toast } = useLive();
  const reports = useApi(() => reportApi.list({ limit: 200 }), [], { initial: [] });
  const recent = useApi(() => eventApi.list({ page_size: 50, status: "completed" }), [], { initial: { items: [] } });
  const [eventId, setEventId] = useState("");
  const { busy, run } = useAction(toast);

  const generate = () => run("gen", async () => {
    const r = await reportApi.generate(Number(eventId));
    await reports.reload(true);
    window.open(reportApi.downloadUrl(r.id, true), "_blank");
    return r;
  }, (r) => `Report #${r.id} generated for event #${r.event_id}`);

  return (
    <>
      <PageHead title="Incident Reports" subtitle="PDF reports with event details, snapshot, AI description and evidence reference." />
      <div className="grid g-live">
        <Panel title="Generated reports" pad={false} actions={<span className="muted mono">{reports.data.length}</span>}>
          <ErrorBox error={reports.error} />
          {!reports.data.length ? <Empty title="No reports yet">Generate one from an event or with the form.</Empty> : (
            <table className="table">
              <thead><tr><th>Report</th><th>Event</th><th>Created</th><th>Size</th><th /></tr></thead>
              <tbody>{reports.data.map((r) => (
                <tr key={r.id}>
                  <td className="mono">#{r.id}</td>
                  <td>{r.event_id ? <Link to={`/events/${r.event_id}`} className="mono">#{r.event_id}</Link> : <span className="muted">deleted</span>}</td>
                  <td className="mono">{fmtDateTime(r.created_at)}</td>
                  <td className="mono">{fmtBytes(r.size_bytes)}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <a className="btn sm" href={reportApi.downloadUrl(r.id, true)} target="_blank" rel="noreferrer">Open</a>{" "}
                    <a className="btn sm" href={reportApi.downloadUrl(r.id)}>Download</a>{" "}
                    <Btn className="sm ghost" icon="trash" onClick={() => window.confirm(`Delete report #${r.id}?`) && run(`d${r.id}`, async () => { await reportApi.remove(r.id); await reports.reload(true); }, "Report deleted")} />
                  </td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Panel>
        <Panel title="Generate report">
          <div className="stack">
            <Field label="Event">
              <select value={eventId} onChange={(e) => setEventId(e.target.value)}>
                <option value="">Select a completed event…</option>
                {recent.data.items.map((e) => <option key={e.id} value={e.id}>#{e.id} · {typeLabel(e.event_type)} · {e.object_class || "—"} · {fmtDateTime(e.start_time)}</option>)}
              </select>
            </Field>
            <Btn icon="report" className="primary" busy={busy === "gen"} disabled={!eventId} onClick={generate}>Generate PDF report</Btn>
          </div>
        </Panel>
      </div>
    </>
  );
}
