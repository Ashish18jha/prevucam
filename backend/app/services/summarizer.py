"""Smart event summarisation.

1. `build_context` turns DB metadata + tracked trajectories into a compact,
   structured description (who/what, where, when, how long, how it moved).
2. If Gemini is configured and enabled it writes the natural-language summary
   from that context (plus the event snapshot). Only finished events are sent –
   never raw camera frames.
3. If Gemini is unavailable or fails, a deterministic template summary is used,
   so every event always gets a description.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import settings as cfg
from app.database.models import Event
from app.utils.logger import get_logger

log = get_logger("summarizer")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TYPE_PHRASE = {
    "object_detection": "detected",
    "zone_violation": "entered",
    "loitering": "loitered in",
    "motion": "motion detected",
}


def _fmt_time(dt: datetime | None) -> str:
    return dt.strftime("%I:%M %p").lstrip("0") if dt else "an unknown time"


def video_clock(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _movement(trajectory: list) -> str | None:
    if not trajectory or len(trajectory) < 2:
        return None
    (_, x0, y0), (_, x1, y1) = trajectory[0], trajectory[-1]
    dx, dy = x1 - x0, y1 - y0
    xs = sorted(p[1] for p in trajectory)
    median = xs[len(xs) // 2]
    still = sum(abs(x - median) < 0.04 for x in xs) / len(xs)
    if still >= 0.6 and xs[-1] - xs[0] >= 0.15:
        return "stood still for most of the time"
    if abs(dx) < 0.08 and abs(dy) < 0.08:
        # little net displacement – distinguish "stood still" from "walked in and back out"
        return "moved back and forth" if xs[-1] - xs[0] >= 0.15 else "stayed mostly in place"
    parts = []
    if abs(dx) >= 0.08:
        parts.append("left to right" if dx > 0 else "right to left")
    if abs(dy) >= 0.08:
        parts.append("towards the camera" if dy > 0 else "away from the camera")
    return "moved " + " and ".join(parts)


def _place(zone: str | None, noun: str) -> str:
    """'Main Gate' -> 'the Main Gate area'; 'Restricted Area' -> 'the Restricted Area'."""
    if not zone:
        return f"the monitored {noun}"
    last = zone.strip().split()[-1].lower()
    return f"the {zone}" if last in {"area", "zone", "lot", "room", "office", "parking"} \
        else f"the {zone} {noun}"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def build_context(event: Event) -> dict:
    meta = event.metadata_json or {}
    objects = []
    for o in event.objects or []:
        objects.append({
            "track_id": o.track_id, "class": o.object_class, "confidence": round(o.max_confidence, 2),
            "zones": o.zones, "seconds_visible": round((o.last_seen - o.first_seen).total_seconds(), 1),
            "movement": _movement(o.trajectory),
        })
    analysis = getattr(event, "analysis", None)
    from_video = event.source == "video"
    clock_known = not from_video or bool(analysis and analysis.recorded_at)
    return {
        "event_id": event.id,
        "source": "uploaded video" if from_video else "live camera",
        "video_name": analysis.original_name if analysis else None,
        "video_timestamp": video_clock(event.video_offset) if from_video else None,
        "video_end_timestamp": video_clock(meta.get("video_event_end")) if from_video else None,
        "wall_clock_known": clock_known,
        "event_type": event.event_type,
        "primary_object": event.object_class,
        "confidence": round(event.confidence or 0, 2),
        "zone": event.zone_name,
        "date": event.start_time.strftime("%Y-%m-%d") if event.start_time else None,
        "time": _fmt_time(event.start_time),
        "start_clock": event.start_time.strftime("%H:%M:%S") if event.start_time and clock_known else None,
        "end_clock": event.end_time.strftime("%H:%M:%S") if event.end_time and clock_known else None,
        "duration_seconds": round(event.duration or 0, 1),
        "loitering_dwell_seconds": meta.get("loitering_dwell"),
        "object_counts": meta.get("object_counts", {}),
        "objects": objects,
        "triggers": meta.get("triggers", [])[:20],
    }


def template_summary(ctx: dict) -> str:
    obj = ctx.get("primary_object") or "object"
    counts = ctx.get("object_counts") or {}
    n = counts.get(obj, 1) or 1
    subject = f"{_article(obj)} {obj}" if n <= 1 else f"{n} {obj}s"
    zone = ctx.get("zone")
    dur = ctx.get("duration_seconds") or 0
    etype = ctx.get("event_type")
    if ctx.get("video_timestamp") and not ctx.get("wall_clock_known"):
        when = f"{ctx['video_timestamp']} in {ctx.get('video_name') or 'the video'}"
    elif ctx.get("video_timestamp"):
        when = f"{ctx.get('time')} ({ctx['video_timestamp']} in the video)"
    else:
        when = ctx.get("time")

    if etype == "loitering":
        dwell = ctx.get("loitering_dwell_seconds") or dur
        text = f"At {when}, {subject} loitered in {_place(zone, 'area')} for about {dwell:.0f} seconds."
    elif etype == "zone_violation":
        text = f"At {when}, {subject} entered {_place(zone, 'area')} and remained there for {dur:.0f} seconds."
    elif etype == "motion":
        text = f"At {when}, motion was detected for {dur:.0f} seconds."
    else:
        where = f" in {_place(zone, 'area')}" if zone else ""
        text = f"At {when}, {subject} was detected{where} and remained in view for {dur:.0f} seconds."

    primary = next((o for o in ctx.get("objects", []) if o["class"] == obj and o.get("movement")), None)
    if primary:
        text += f" The {obj} {primary['movement']}."
    others = {k: v for k, v in counts.items() if k != obj}
    if others:
        text += " Also observed: " + ", ".join(f"{v} {k}{'s' if v > 1 else ''}" for k, v in others.items()) + "."
    return text


def gemini_summary(ctx: dict, snapshot: Path | None = None) -> str:
    if not cfg.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    prompt = (
        "You are the incident-summary module of a security camera system. "
        "Write a concise, factual 1-3 sentence summary of this event for a security log. "
        "Use the structured detection data as ground truth (times, durations, zones, counts); "
        "you may use the attached snapshot only to add clearly visible, non-identifying context "
        "(e.g. clothing colour, carrying a bag). Do not speculate about identity or intent. "
        "Use 12-hour clock time when wall_clock_known is true; otherwise refer to the position in the "
        "video (video_timestamp, mm:ss). Plain text only.\n\nEvent data:\n" + json.dumps(ctx, default=str)
    )
    parts: list[dict] = [{"text": prompt}]
    if snapshot and snapshot.exists():
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                                      "data": base64.b64encode(snapshot.read_bytes()).decode()}})
    log.info("Gemini request for event %s (model=%s)", ctx.get("event_id"), cfg.GEMINI_MODEL)
    resp = httpx.post(
        GEMINI_URL.format(model=cfg.GEMINI_MODEL),
        headers={"x-goog-api-key": cfg.GEMINI_API_KEY, "Content-Type": "application/json"},
        json={"contents": [{"parts": parts}],
              "generationConfig": {"temperature": 0.2, "maxOutputTokens": 300}},
        timeout=cfg.GEMINI_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected Gemini response: {str(data)[:200]}") from exc
    if not text:
        raise RuntimeError("Gemini returned an empty summary")
    return text


def summarize(event: Event, use_gemini: bool = True) -> tuple[str, str, str | None]:
    """Returns (summary, source, ai_error).

    source is 'gemini' when Gemini wrote the text, otherwise 'template' (deterministic description
    built from detections). ai_error explains why the AI summary is unavailable.
    """
    ctx = build_context(event)
    if not use_gemini:
        return template_summary(ctx), "template", "Gemini summaries are disabled in Notifications & AI settings."
    if not cfg.GEMINI_API_KEY:
        return template_summary(ctx), "template", "Gemini is not configured (GEMINI_API_KEY is empty)."
    snapshot = cfg.storage_dir / event.snapshot_path if event.snapshot_path else None
    try:
        return gemini_summary(ctx, snapshot), "gemini", None
    except Exception as exc:
        log.warning("Gemini summary failed for event %d, using template: %s", event.id, exc)
        return template_summary(ctx), "template", f"Gemini request failed: {str(exc)[:300]}"
