import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import EventTable from "../components/EventTable";
import { Btn, Empty, ErrorBox, PageHead, Panel } from "../components/UI";
import { useLive } from "../context/LiveContext";
import { useApi } from "../hooks/useApi";
import { detectionApi, eventApi, videoAnalysisApi, zoneApi } from "../services/api";

const EMPTY = { source: "", analysis_id: "", date: "", start_time: "", end_time: "", object_class: "", zone: "", event_type: "", keyword: "", min_duration: "", max_duration: "" };

export default function Events() {
  const { eventTick } = useLive();
  const [search] = useSearchParams();
  const initial = { ...EMPTY, analysis_id: search.get("analysis_id") || "", source: search.get("analysis_id") ? "video" : "" };
  const [form, setForm] = useState(initial);
  const [query, setQuery] = useState(initial);
  const analyses = useApi(videoAnalysisApi.list, [], { initial: [] });
  const [page, setPage] = useState(1);
  const zones = useApi(zoneApi.list, [], { initial: [] });
  const classes = useApi(detectionApi.classes, [], { initial: { classes: [], relevant: [] } });
  const params = Object.fromEntries(Object.entries({ ...query, page, page_size: 20 }).filter(([, v]) => v !== "" && v != null));
  const events = useApi(() => eventApi.list(params), [JSON.stringify(params), eventTick]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const apply = (e) => { e?.preventDefault(); setPage(1); setQuery(form); };
  const reset = () => { setForm(EMPTY); setQuery(EMPTY); setPage(1); };
  const total = events.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 20));

  return (
    <>
      <PageHead title="Events" subtitle="Search recorded incidents by date, time, object, zone, type, duration or keyword." />
      <Panel>
        <form onSubmit={apply} className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
          <label className="field"><span>Source</span>
            <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value, analysis_id: e.target.value === "live" ? "" : form.analysis_id })}>
              <option value="">Live + videos</option>
              <option value="live">Live camera</option>
              <option value="video">Uploaded videos</option>
            </select>
          </label>
          <label className="field"><span>Analysis / video</span>
            <select value={form.analysis_id} disabled={form.source === "live"} onChange={(e) => setForm({ ...form, analysis_id: e.target.value, source: e.target.value ? "video" : form.source })}>
              <option value="">Any</option>
              {analyses.data.map((a) => <option key={a.analysis_id} value={a.analysis_id}>#{a.analysis_id} · {a.original_name}</option>)}
            </select>
          </label>
          <label className="field"><span>Date</span><input type="date" value={form.date} onChange={set("date")} /></label>
          <label className="field"><span>From time</span><input type="time" value={form.start_time} onChange={set("start_time")} disabled={!form.date} /></label>
          <label className="field"><span>To time</span><input type="time" value={form.end_time} onChange={set("end_time")} disabled={!form.date} /></label>
          <label className="field"><span>Object</span>
            <select value={form.object_class} onChange={set("object_class")}>
              <option value="">Any</option>
              {classes.data.relevant.length > 0 && <optgroup label="Relevant">{classes.data.relevant.map((c) => <option key={c} value={c}>{c}</option>)}</optgroup>}
              <optgroup label="All classes">{classes.data.classes.filter((c) => !classes.data.relevant.includes(c)).map((c) => <option key={c} value={c}>{c}</option>)}</optgroup>
            </select>
          </label>
          <label className="field"><span>Zone</span>
            <select value={form.zone} onChange={set("zone")}>
              <option value="">Any</option>
              {zones.data.map((z) => <option key={z.id} value={z.name}>{z.name}</option>)}
            </select>
          </label>
          <label className="field"><span>Type</span>
            <select value={form.event_type} onChange={set("event_type")}>
              <option value="">Any</option>
              <option value="object_detection">Object detection</option>
              <option value="zone_violation">Zone violation</option>
              <option value="loitering">Loitering</option>
              <option value="motion">Motion</option>
            </select>
          </label>
          <label className="field"><span>Min duration (s)</span><input type="number" min="0" value={form.min_duration} onChange={set("min_duration")} /></label>
          <label className="field"><span>Max duration (s)</span><input type="number" min="0" value={form.max_duration} onChange={set("max_duration")} /></label>
          <label className="field" style={{ gridColumn: "span 2" }}><span>Keyword</span><input placeholder="Search summaries, zones, objects…" value={form.keyword} onChange={set("keyword")} /></label>
          <div className="row" style={{ alignSelf: "end" }}>
            <Btn icon="search" className="primary" type="submit">Search</Btn>
            <Btn className="ghost" type="button" onClick={reset}>Reset</Btn>
          </div>
        </form>
      </Panel>
      <div style={{ height: 16 }} />
      <ErrorBox error={events.error} />
      <Panel pad={false} title={<span className="muted">{total} matching event{total === 1 ? "" : "s"}</span>}
        actions={pages > 1 && (
          <div className="row">
            <Btn className="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Btn>
            <span className="mono muted">{page}/{pages}</span>
            <Btn className="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Btn>
          </div>
        )}>
        {events.loading && !events.data ? <Empty title="Loading…" /> :
          events.data?.items?.length ? <EventTable events={events.data.items} /> :
          <Empty title="No events match these filters" />}
      </Panel>
    </>
  );
}
