import { useEffect, useState } from "react";
import ZoneEditor from "../components/ZoneEditor";
import { Badge, Btn, Empty, ErrorBox, Field, PageHead, Panel, Switch } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useAction, useApi } from "../hooks/useApi";
import { cameraApi, videoAnalysisApi, zoneApi } from "../services/api";

const COLORS = ["#ef4444", "#f59e0b", "#22d3ee", "#34d399", "#a78bfa", "#f472b6"];
const blank = () => ({ id: null, name: "", zone_type: "monitored", color: COLORS[Math.floor(Math.random() * COLORS.length)],
  active: true, trigger_on_entry: true, loitering_enabled: true, loitering_seconds: "", points: [] });

export default function Zones() {
  const { camera, toast } = useLive();
  const zones = useApi(zoneApi.list, [], { initial: [] });
  const { busy, run } = useAction(toast);
  const [draft, setDraft] = useState(null);
  const [mode, setMode] = useState(null);
  const [bg, setBg] = useState(null);
  const videos = useApi(videoAnalysisApi.list, [], { initial: [] });
  // background to draw on: the live camera, or a frame of an uploaded video ("v<id>")
  const [bgSource, setBgSource] = useState("live");

  const refreshBg = () => {
    if (bgSource === "live") setBg(camera?.running ? cameraApi.snapshotUrl(false) : null);
    else setBg(videoAnalysisApi.frameUrl(Number(bgSource.slice(1))));
  };
  useEffect(() => {
    if (bgSource === "live" && !camera?.running && videos.data.length) setBgSource(`v${videos.data[0].analysis_id}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videos.data.length, camera?.running]);
  useEffect(refreshBg, [bgSource, camera?.running]); // eslint-disable-line react-hooks/exhaustive-deps

  const startNew = (m) => { setDraft(blank()); setMode(m); };
  const edit = (z) => { setDraft({ ...z, loitering_seconds: z.loitering_seconds ?? "" }); setMode(null); };
  const cancel = () => { setDraft(null); setMode(null); };

  const save = () => run("save", async () => {
    const body = { name: draft.name.trim(), zone_type: draft.zone_type, color: draft.color, active: draft.active,
      trigger_on_entry: draft.trigger_on_entry, loitering_enabled: draft.loitering_enabled,
      loitering_seconds: draft.loitering_seconds === "" ? null : Number(draft.loitering_seconds), points: draft.points };
    if (draft.id) await zoneApi.update(draft.id, body); else await zoneApi.create(body);
    await zones.reload(true);
    cancel();
  }, `Zone "${draft?.name}" saved`);

  const remove = (z) => window.confirm(`Delete zone "${z.name}"?`) &&
    run(`del${z.id}`, async () => { await zoneApi.remove(z.id); await zones.reload(true); if (draft?.id === z.id) cancel(); }, "Zone deleted");
  const toggle = (z, active) => run(`t${z.id}`, async () => { await zoneApi.update(z.id, { active }); await zones.reload(true); });

  const shown = zones.data.filter((z) => z.id !== draft?.id);
  const valid = draft && draft.name.trim() && draft.points.length >= 3;

  return (
    <>
      <PageHead title="Smart Zones" subtitle="Draw regions on the camera view. Relevant objects entering trigger zones create events; dwell beyond the threshold raises loitering.">
        <Btn icon="plus" className="primary" onClick={() => startNew("polygon")}>Draw polygon</Btn>
        <Btn icon="plus" onClick={() => startNew("rect")}>Draw rectangle</Btn>
      </PageHead>
      <ErrorBox error={zones.error} />
      <div className="grid g-live">
        <Panel title={mode ? (mode === "polygon" ? "Click to add points · double-click or Finish to close" : "Drag to draw a rectangle") : "Camera view"}
          actions={
            <div className="row">
              <select value={bgSource} onChange={(e) => setBgSource(e.target.value)} style={{ height: 28, maxWidth: 230 }} aria-label="Background frame">
                <option value="live">Live camera{camera?.running ? "" : " (stopped)"}</option>
                {videos.data.map((v) => <option key={v.analysis_id} value={`v${v.analysis_id}`}>Video: {v.original_name}</option>)}
              </select>
              <Btn className="sm ghost" icon="restart" onClick={refreshBg} disabled={bgSource === "live" && !camera?.running}>Refresh frame</Btn>
            </div>
          }>
          <ZoneEditor background={bg} zones={draft ? [...shown, ...(!mode && draft.points.length >= 3 ? [{ ...draft, id: draft.id ?? -1, name: draft.name || "New zone" }] : [])] : zones.data}
            highlightId={draft ? draft.id ?? -1 : null} mode={mode} points={mode ? draft?.points || [] : []}
            onPoints={(points) => setDraft({ ...draft, points })} onComplete={() => setMode(null)} />
          {!bg && <div className="note" style={{ marginTop: 10 }}>Start the camera, or pick an uploaded video above, to draw on a real frame. Zones are stored in normalised coordinates, so the same zone applies to the live camera and to uploaded videos at any resolution.</div>}
          {mode === "polygon" && (
            <div className="row" style={{ marginTop: 10 }}>
              <span className="muted">{draft.points.length} point(s)</span>
              <Btn className="sm" onClick={() => setDraft({ ...draft, points: draft.points.slice(0, -1) })} disabled={!draft.points.length}>Undo point</Btn>
              <Btn className="sm primary" onClick={() => setMode(null)} disabled={draft.points.length < 3}>Finish shape</Btn>
            </div>
          )}
        </Panel>

        <div className="stack">
          {draft && (
            <Panel title={draft.id ? `Edit zone` : "New zone"} actions={<Btn className="sm ghost" onClick={cancel}>Cancel</Btn>}>
              <div className="stack">
                <Field label="Name"><input value={draft.name} placeholder="e.g. Main Gate" onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
                <div className="form-grid" style={{ gridTemplateColumns: "1fr auto" }}>
                  <Field label="Type">
                    <select value={draft.zone_type} onChange={(e) => setDraft({ ...draft, zone_type: e.target.value })}>
                      <option value="monitored">Monitored</option><option value="restricted">Restricted</option>
                    </select>
                  </Field>
                  <Field label="Colour"><input type="color" value={draft.color} onChange={(e) => setDraft({ ...draft, color: e.target.value })} /></Field>
                </div>
                <Switch checked={draft.trigger_on_entry} onChange={(v) => setDraft({ ...draft, trigger_on_entry: v })} label="Trigger event on entry" />
                <Switch checked={draft.loitering_enabled} onChange={(v) => setDraft({ ...draft, loitering_enabled: v })} label="Loitering detection" />
                <Field label="Loitering threshold (s)" hint="Empty = use the global threshold"><input type="number" min="1" value={draft.loitering_seconds} onChange={(e) => setDraft({ ...draft, loitering_seconds: e.target.value })} disabled={!draft.loitering_enabled} /></Field>
                <Switch checked={draft.active} onChange={(v) => setDraft({ ...draft, active: v })} label="Active" />
                <div className="row">
                  <Btn icon="check" className="primary" busy={busy === "save"} disabled={!valid} onClick={save}>Save zone</Btn>
                  <Btn onClick={() => { setDraft({ ...draft, points: [] }); setMode("polygon"); }}>Redraw</Btn>
                </div>
                {!valid && <span className="field-hint">Name and a shape with ≥ 3 points are required.</span>}
              </div>
            </Panel>
          )}
          <Panel title="Zones" pad={false} actions={<span className="muted mono">{zones.data.length}</span>}>
            {!zones.data.length ? <Empty title="No zones yet">Draw one to enable zone violation and loitering alerts.</Empty> : (
              <table className="table">
                <tbody>
                  {zones.data.map((z) => (
                    <tr key={z.id}>
                      <td style={{ width: 12 }}><span className="dot" style={{ color: z.color, width: 10, height: 10 }} /></td>
                      <td><div style={{ fontWeight: 600 }}>{z.name}</div>
                        <div className="row" style={{ gap: 6, marginTop: 4 }}>
                          <Badge tone={z.zone_type === "restricted" ? "red" : "cyan"}>{z.zone_type}</Badge>
                          {z.trigger_on_entry && <Badge>entry</Badge>}
                          {z.loitering_enabled && <Badge>loiter {z.loitering_seconds ? `${z.loitering_seconds}s` : "global"}</Badge>}
                        </div>
                      </td>
                      <td><Switch checked={z.active} onChange={(v) => toggle(z, v)} /></td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        <Btn className="sm ghost" onClick={() => edit(z)}>Edit</Btn>
                        <Btn className="sm ghost" icon="trash" busy={busy === `del${z.id}`} onClick={() => remove(z)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}
