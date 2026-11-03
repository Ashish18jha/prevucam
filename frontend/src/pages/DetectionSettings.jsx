import { Btn, Empty, ErrorBox, Field, PageHead, Panel, Switch, Badge } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useAction, useApi } from "../hooks/useApi";
import { useSettings } from "../hooks/useSettings";
import { detectionApi } from "../services/api";

const KEYS = ["motion_sensitivity", "motion_min_area", "detection_interval", "yolo_confidence", "relevant_objects",
  "pre_event_seconds", "post_event_seconds", "max_event_seconds", "event_cooldown_seconds", "trigger_on_relevant_object",
  "trigger_on_zone_entry", "trigger_on_loitering", "trigger_on_motion", "loitering_seconds", "loitering_classes"];
const COMMON = ["person", "car", "motorcycle", "bicycle", "bus", "truck", "dog", "cat", "bird", "backpack", "handbag", "suitcase"];

function Range({ label, value, min, max, step = 1, unit = "", onChange, hint }) {
  return (
    <Field label={<span className="row between" style={{ width: "100%" }}>{label}<span className="mono" style={{ color: "var(--text)" }}>{value}{unit}</span></span>} hint={hint}>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  );
}

function ClassPicker({ selected, onChange, classes }) {
  const toggle = (c) => onChange(selected.includes(c) ? selected.filter((x) => x !== c) : [...selected, c].sort());
  const extra = classes.filter((c) => !COMMON.includes(c));
  return (
    <div className="stack">
      <div className="chip-list">{COMMON.map((c) => <button type="button" key={c} className={`chip ${selected.includes(c) ? "on" : ""}`} onClick={() => toggle(c)}>{c}</button>)}</div>
      <details>
        <summary className="muted" style={{ cursor: "pointer", fontSize: 12.5 }}>All {classes.length} model classes</summary>
        <div className="chip-list" style={{ marginTop: 10 }}>{extra.map((c) => <button type="button" key={c} className={`chip ${selected.includes(c) ? "on" : ""}`} onClick={() => toggle(c)}>{c}</button>)}</div>
      </details>
    </div>
  );
}

export default function DetectionSettings() {
  const { toast } = useLive();
  const { form, set, save, revert, dirty, busy, error } = useSettings(KEYS);
  const model = useApi(detectionApi.model, []);
  const classes = useApi(detectionApi.classes, [], { initial: { classes: COMMON } });
  const { busy: mBusy, run } = useAction(toast);
  if (error) return <ErrorBox error={error} />;
  if (!form) return <Empty title="Loading settings…" />;

  return (
    <>
      <PageHead title="Detection Settings" subtitle="Changes apply to the running pipeline immediately and persist across restarts.">
        <Btn className="ghost" onClick={revert} disabled={!dirty}>Revert</Btn>
        <Btn icon="check" className="primary" busy={busy} disabled={!dirty} onClick={save}>Save changes</Btn>
      </PageHead>
      <div className="grid g-2">
        <Panel title="Relevant objects" actions={<span className="muted">{form.relevant_objects.length} selected</span>}>
          <p className="muted" style={{ marginTop: 0 }}>Only these classes create events. Everything else is still detected and drawn (grey) but ignored.</p>
          <ClassPicker selected={form.relevant_objects} classes={classes.data.classes} onChange={(v) => set("relevant_objects", v)} />
        </Panel>
        <Panel title="YOLO detector" actions={model.data && (model.data.available ? <Badge tone="green" dot>Loaded</Badge> : <Badge tone="red" dot>Unavailable</Badge>)}>
          <div className="stack">
            <Range label="Confidence threshold" value={form.yolo_confidence} min={0.1} max={0.95} step={0.05} onChange={(v) => set("yolo_confidence", v)} hint="Detections below this score are discarded." />
            <Range label="Detection interval" value={form.detection_interval} min={1} max={15} unit=" frames" onChange={(v) => set("detection_interval", v)} hint="Run YOLO every N frames while motion / tracks / an event are active." />
            {model.data && <div className="note mono" style={{ fontSize: 12 }}>{model.data.model_path} · imgsz {model.data.imgsz}{model.data.error ? ` · ${model.data.error}` : ""}</div>}
            {model.data && !model.data.available && <Btn busy={mBusy === "reload"} onClick={() => run("reload", async () => { await detectionApi.reloadModel(); await model.reload(true); }, "Model reload attempted")}>Retry loading model</Btn>}
          </div>
        </Panel>
        <Panel title="Motion gate">
          <div className="stack">
            <Range label="Motion sensitivity" value={form.motion_sensitivity} min={1} max={100} onChange={(v) => set("motion_sensitivity", v)} hint="Higher = smaller pixel changes count as motion." />
            <Range label="Minimum motion area" value={form.motion_min_area} min={50} max={20000} step={50} unit=" px²" onChange={(v) => set("motion_min_area", v)} hint="Ignore changes smaller than this (noise, leaves, rain)." />
            <Switch checked={form.trigger_on_motion} onChange={(v) => set("trigger_on_motion", v)} label="Record motion-only events (no object required)" />
          </div>
        </Panel>
        <Panel title="Event recording">
          <div className="stack">
            <Range label="Pre-event buffer" value={form.pre_event_seconds} min={0} max={30} step={1} unit=" s" onChange={(v) => set("pre_event_seconds", v)} hint="Footage kept in the circular buffer and prepended to every event." />
            <Range label="Post-event recording" value={form.post_event_seconds} min={1} max={60} step={1} unit=" s" onChange={(v) => set("post_event_seconds", v)} hint="Keep recording this long after the last relevant detection." />
            <Range label="Maximum event length" value={form.max_event_seconds} min={10} max={600} step={10} unit=" s" onChange={(v) => set("max_event_seconds", v)} />
            <Range label="Cooldown between events" value={form.event_cooldown_seconds} min={0} max={60} unit=" s" onChange={(v) => set("event_cooldown_seconds", v)} />
          </div>
        </Panel>
        <Panel title="Event triggers">
          <div className="stack">
            <Switch checked={form.trigger_on_relevant_object} onChange={(v) => set("trigger_on_relevant_object", v)} label="Any relevant object in view" />
            <Switch checked={form.trigger_on_zone_entry} onChange={(v) => set("trigger_on_zone_entry", v)} label="Relevant object enters a trigger zone" />
            <Switch checked={form.trigger_on_loitering} onChange={(v) => set("trigger_on_loitering", v)} label="Loitering inside a zone" />
            <div className="note">Turn off “any relevant object” to record only zone violations and loitering.</div>
          </div>
        </Panel>
        <Panel title="Loitering">
          <div className="stack">
            <Range label="Global loitering threshold" value={form.loitering_seconds} min={5} max={300} step={5} unit=" s" onChange={(v) => set("loitering_seconds", v)} hint="Zones can override this individually." />
            <Field label="Classes that can loiter">
              <div className="chip-list">{["person", "car", "motorcycle", "bicycle", "dog"].map((c) => (
                <button type="button" key={c} className={`chip ${form.loitering_classes.includes(c) ? "on" : ""}`}
                  onClick={() => set("loitering_classes", form.loitering_classes.includes(c) ? form.loitering_classes.filter((x) => x !== c) : [...form.loitering_classes, c])}>{c}</button>
              ))}</div>
            </Field>
          </div>
        </Panel>
      </div>
    </>
  );
}
