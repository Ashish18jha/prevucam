from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


def _now() -> datetime:
    return datetime.now()


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # Polygon in normalised coordinates [[x, y], ...] with 0..1 range (resolution independent)
    points: Mapped[list] = mapped_column(JSON)
    zone_type: Mapped[str] = mapped_column(String(30), default="monitored")  # monitored | restricted
    color: Mapped[str] = mapped_column(String(20), default="#f59e0b")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger_on_entry: Mapped[bool] = mapped_column(Boolean, default=True)
    loitering_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    loitering_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)  # None -> global
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class VideoAnalysis(Base):
    """One uploaded, prerecorded video and the state of its analysis run."""

    __tablename__ = "video_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255), unique=True)  # safe stored name in storage/uploads
    file_path: Mapped[str] = mapped_column(String(500))  # relative to storage/
    preview_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # browser-playable copy
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    total_frames: Mapped[int] = mapped_column(Integer, default=0)
    codec: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # wall time of video frame 0
    # uploaded | queued | processing | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    frames_processed: Mapped[int] = mapped_column(Integer, default=0)
    current_time: Mapped[float] = mapped_column(Float, default=0.0)  # seconds into the video
    events_detected: Mapped[int] = mapped_column(Integer, default=0)
    objects_detected: Mapped[int] = mapped_column(Integer, default=0)  # unique confirmed tracks
    zone_violations: Mapped[int] = mapped_column(Integer, default=0)
    loitering_events: Mapped[int] = mapped_column(Integer, default=0)
    object_counts: Mapped[dict] = mapped_column(JSON, default=dict)  # unique tracks per class
    detections_run: Mapped[int] = mapped_column(Integer, default=0)  # frames YOLO actually ran on
    processing_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)  # object_detection | zone_violation | loitering | motion
    status: Mapped[str] = mapped_column(String(20), default="recording", index=True)  # recording | processing | completed | failed
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    object_class: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True)
    zone_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    video_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # gemini | template
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    notification_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | sent | partial | failed | skipped
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False)
    summary_error: Mapped[str | None] = mapped_column(Text, nullable=True)  # why Gemini was not used / failed
    source: Mapped[str] = mapped_column(String(10), default="live", index=True)  # live | video
    analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_analyses.id", ondelete="SET NULL"), nullable=True, index=True)
    video_offset: Mapped[float | None] = mapped_column(Float, nullable=True)  # seconds into the uploaded video
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    zone: Mapped[Zone | None] = relationship(lazy="joined")
    analysis: Mapped[VideoAnalysis | None] = relationship(lazy="joined")
    objects: Mapped[list["EventObject"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )


class EventObject(Base):
    __tablename__ = "event_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(Integer)
    object_class: Mapped[str] = mapped_column(String(50), index=True)
    max_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=_now)
    zones: Mapped[list] = mapped_column(JSON, default=list)
    trajectory: Mapped[list] = mapped_column(JSON, default=list)  # [[t_offset, cx, cy], ...] normalised

    event: Mapped[Event] = relationship(back_populates="objects")


class LoiteringRecord(Base):
    __tablename__ = "loitering_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(Integer, index=True)
    object_class: Mapped[str] = mapped_column(String(50), default="person")
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True)
    zone_name: Mapped[str] = mapped_column(String(100))
    enter_time: Mapped[datetime] = mapped_column(DateTime)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    threshold: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | triggered | cleared
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_analyses.id", ondelete="CASCADE"), nullable=True, index=True)


class SettingEntry(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(20))  # telegram | email
    status: Mapped[str] = mapped_column(String(20))  # sent | failed | skipped
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    event: Mapped[Event | None] = relationship(back_populates="notifications")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Timelapse(Base):
    __tablename__ = "timelapses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing | completed | failed
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
