import { useState } from "react";
import { Btn, Empty, ErrorBox, Field, PageHead, Panel, StatusBadge } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useAction, useApi } from "../hooks/useApi";
import { mediaUrl, timelapseApi } from "../services/api";
import { fmtBytes, fmtDateTime, fmtDuration, todayISO } from "../utils/format";

export default function Timelapse() {
  const { toast } = useLive();
  const list = useApi(timelapseApi.list, [], { initial: [], interval: 3000 });
  const [date, setDate] = useState(todayISO());
  const [speed, setSpeed] = useState(4);
  const [selected, setSelected] = useState(null);
  const { busy, run } = useAction(toast);

  const generate = () => run("gen", async () => { const t = await timelapseApi.generate(date, speed); await list.reload(true); setSelected(t.id); return t; },
    (t) => `Generating timelapse for ${t.date}…`);
  const current = list.data.find((t) => t.id === selected) || list.data.find((t) => t.status === "completed");

  return (
    <>
      <PageHead title="Daily Timelapse" subtitle="Condenses every event clip of a day, in chronological order, into one time-stamped video." />
      <div className="grid g-live">
        <Panel title={current ? `Timelapse · ${current.date}` : "Timelapse"} actions={current?.status === "completed" && <a className="btn sm" href={timelapseApi.downloadUrl(current.id)}>Download</a>}>
          {current?.status === "completed" ? (
            <div className="feed"><video key={current.id} src={mediaUrl(current.video_url)} controls autoPlay muted /></div>
          ) : current?.status === "processing" ? <Empty title="Generating…">Clips are being condensed. This updates automatically.</Empty>
            : <Empty title="Nothing to show yet">Pick a date with recorded events and generate a timelapse.</Empty>}
          {current?.status === "completed" && <div className="muted" style={{ marginTop: 10, fontSize: 12.5 }}>{current.event_count} events · {fmtDuration(current.duration)} · {fmtBytes(current.size_bytes)}</div>}
        </Panel>
        <div className="stack">
          <Panel title="Generate">
            <div className="stack">
              <Field label="Date"><input type="date" value={date} max={todayISO()} onChange={(e) => setDate(e.target.value)} /></Field>
              <Field label={`Speed-up: ${speed}×`} hint="Keep one of every N frames."><input type="range" min="1" max="20" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} /></Field>
              <Btn icon="film" className="primary" busy={busy === "gen"} disabled={!date} onClick={generate}>Generate timelapse</Btn>
            </div>
          </Panel>
          <Panel title="History" pad={false}>
            <ErrorBox error={list.error} />
            {!list.data.length ? <Empty title="No timelapses yet" /> : (
              <table className="table">
                <tbody>{list.data.map((t) => (
                  <tr key={t.id} className="clickable" onClick={() => setSelected(t.id)} style={t.id === current?.id ? { background: "var(--panel-2)" } : null}>
                    <td className="mono">{t.date}</td>
                    <td><StatusBadge status={t.status} /></td>
                    <td className="muted" style={{ fontSize: 12 }}>{t.status === "failed" ? t.error : `${t.event_count} events · ${fmtDuration(t.duration)}`}<div className="faint">{fmtDateTime(t.created_at)}</div></td>
                    <td><Btn className="sm ghost" icon="trash" onClick={(e) => { e.stopPropagation(); window.confirm("Delete this timelapse?") && run(`d${t.id}`, async () => { await timelapseApi.remove(t.id); await list.reload(true); }, "Deleted"); }} /></td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}
