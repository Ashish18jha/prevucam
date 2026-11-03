"""PDF incident reports (ReportLab)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import settings as cfg
from app.database.database import session_scope
from app.database.models import Event, Report
from app.services.event_manager import rel_storage
from app.utils.logger import get_logger

log = get_logger("reports")

ACCENT = colors.HexColor("#0e7490")
DARK = colors.HexColor("#0f172a")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], textColor=DARK, fontSize=20, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], textColor=colors.HexColor("#475569"), fontSize=9),
        "h": ParagraphStyle("h", parent=base["Heading2"], textColor=ACCENT, fontSize=12, spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=10, leading=14),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontSize=9.5, leading=12),
    }


def build_pdf(event: Event, out_path: Path) -> Path:
    st = _styles()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"PreVuCam Incident Report #{event.id}", author="PreVuCam")
    story = [
        Paragraph("PREVUCAM INCIDENT REPORT", st["title"]),
        Paragraph(f"Generated {datetime.now():%Y-%m-%d %H:%M:%S} · AI-Enhanced Event-Driven Surveillance", st["sub"]),
        Spacer(1, 8),
    ]
    meta = event.metadata_json or {}
    from app.services.summarizer import video_clock

    rows = [
        ("Event ID", f"#{event.id}"),
        ("Date", event.start_time.strftime("%Y-%m-%d")),
        ("Time", f"{event.start_time:%H:%M:%S}" + (f" – {event.end_time:%H:%M:%S}" if event.end_time else "")),
        ("Event Type", event.event_type.replace("_", " ").title()),
        ("Object", event.object_class or "-"),
        ("Confidence", f"{event.confidence * 100:.1f}%" if event.confidence else "-"),
        ("Zone", event.zone_name or "-"),
        ("Duration", f"{event.duration:.1f} s"),
        ("Clip length", f"{meta.get('video_duration', 0):.1f} s (incl. {meta.get('pre_event_seconds', 0):.1f} s pre-event)"),
        ("Status", event.status),
    ]
    if event.source == "video":
        name = event.analysis.original_name if event.analysis else "deleted upload"
        rows[1:1] = [("Analysis ID", f"#{event.analysis_id}" if event.analysis_id else "-"),
                     ("Source video", name),
                     ("Video timestamp", f"{video_clock(meta.get('video_event_start', event.video_offset))} – "
                                         f"{video_clock(meta.get('video_event_end'))} "
                                         f"(clip {video_clock(meta.get('video_clip_start'))} – "
                                         f"{video_clock(meta.get('video_clip_end'))})")]
    else:
        rows.insert(1, ("Source", "Live camera"))
    table = Table([[Paragraph(f"<b>{k}</b>", st["cell"]), Paragraph(str(v), st["cell"])] for k, v in rows],
                  colWidths=[40 * mm, 130 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e2e8f0")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [Paragraph("Event Details", st["h"]), table]

    snap = cfg.storage_dir / event.snapshot_path if event.snapshot_path else None
    if snap and snap.exists():
        img = Image(str(snap))
        max_w = 170 * mm
        ratio = img.imageHeight / float(img.imageWidth)
        img.drawWidth, img.drawHeight = max_w, max_w * ratio
        story += [Paragraph("Snapshot", st["h"]), img]

    if event.summary_source == "gemini":
        story += [Paragraph("AI-Generated Description (Gemini)", st["h"]),
                  Paragraph((event.summary or "").replace("\n", "<br/>"), st["body"])]
    else:
        story += [Paragraph("AI-Generated Description", st["h"]),
                  Paragraph("<i>AI summary unavailable.</i>"
                            + (f" <font color='#64748b'>({event.summary_error})</font>" if event.summary_error else ""),
                            st["body"]),
                  Spacer(1, 4),
                  Paragraph("<b>Rule-based description:</b> " + (event.summary or "No description available."),
                            st["body"])]

    if event.objects:
        obj_rows = [["Track", "Object", "Max conf.", "Visible", "Zones"]]
        for o in event.objects:
            obj_rows.append([f"#{o.track_id}", o.object_class, f"{o.max_confidence * 100:.0f}%",
                             f"{(o.last_seen - o.first_seen).total_seconds():.1f} s", ", ".join(o.zones) or "-"])
        t2 = Table(obj_rows, colWidths=[20 * mm, 35 * mm, 25 * mm, 25 * mm, 65 * mm])
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ]))
        story += [Paragraph("Tracked Objects", st["h"]), t2]

    story += [Paragraph("Evidence", st["h"]),
              Paragraph(f"Video reference: <font face='Courier'>storage/{event.video_path or 'not available'}</font>", st["body"])]
    doc.build(story)
    return out_path


def generate_event_report(event_id: int) -> Report:
    with session_scope() as db:
        event = db.get(Event, event_id)
        if event is None:
            raise LookupError(f"Event {event_id} not found")
        if event.status in ("recording",):
            raise ValueError("Event is still recording; try again when it completes")
        path = cfg.subdir("reports") / f"incident_event_{event_id}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        build_pdf(event, path)
        report = Report(event_id=event_id, file_path=rel_storage(path), size_bytes=path.stat().st_size)
        db.add(report)
        db.flush()
        log.info("PDF report %d generated for event %d", report.id, event_id)
        return report
