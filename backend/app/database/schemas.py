from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

EventType = Literal["object_detection", "zone_violation", "loitering", "motion"]
SourceType = Literal["browser", "webcam", "rtsp", "file", "picamera"]


def _local_iso(value: datetime | None) -> str | None:
    """Datetimes are stored as naive server-local time; emit them with the server's UTC offset."""
    if value is None:
        return None
    return (value.astimezone() if value.tzinfo is None else value).isoformat()


class LocalTimeModel(BaseModel):
    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_dt(self, value):
        return _local_iso(value) if isinstance(value, datetime) else value


class ORMModel(LocalTimeModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


# ---------------------------------------------------------------- camera ----
class CameraStartRequest(BaseModel):
    source_type: SourceType | None = Field(None, description="Overrides the configured source type")
    source: str | None = Field(None, description="Webcam index, RTSP URL, or video file path / uploaded file name")
    loop: bool | None = Field(None, description="Loop video files")


class CameraStatus(LocalTimeModel):
    running: bool
    connected: bool
    source_type: str
    source: str
    fps: float
    resolution: list[int]
    frames_processed: int
    last_frame_at: datetime | None
    error: str | None
    motion: bool
    detector_available: bool
    detector_error: str | None
    active_event_id: int | None
    tracks: int
    webcam_connected: bool = False  # browser webcam currently streaming frames
    webcam_label: str | None = None


class VideoUploadResponse(BaseModel):
    filename: str
    path: str
    size_bytes: int
    frames: int
    fps: float
    width: int
    height: int


# ----------------------------------------------------------------- zones ----
class ZoneBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    points: list[list[float]] = Field(..., description="Polygon points normalised 0..1: [[x, y], ...]")
    zone_type: Literal["monitored", "restricted"] = "monitored"
    color: str = Field("#f59e0b", pattern=r"^#[0-9a-fA-F]{6}$")
    active: bool = True
    trigger_on_entry: bool = True
    loitering_enabled: bool = True
    loitering_seconds: float | None = Field(None, gt=0, le=3600)

    @field_validator("points")
    @classmethod
    def _valid_polygon(cls, pts: list[list[float]]) -> list[list[float]]:
        if len(pts) < 3:
            raise ValueError("A zone needs at least 3 points")
        for p in pts:
            if len(p) != 2:
                raise ValueError("Each point must be [x, y]")
            if not (0.0 <= p[0] <= 1.0 and 0.0 <= p[1] <= 1.0):
                raise ValueError("Points must be normalised between 0 and 1")
        return [[round(float(x), 5), round(float(y), 5)] for x, y in pts]


class ZoneCreate(ZoneBase):
    pass


class ZoneUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    points: list[list[float]] | None = None
    zone_type: Literal["monitored", "restricted"] | None = None
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    active: bool | None = None
    trigger_on_entry: bool | None = None
    loitering_enabled: bool | None = None
    loitering_seconds: float | None = Field(None, gt=0, le=3600)

    @field_validator("points")
    @classmethod
    def _valid_polygon(cls, pts):
        return None if pts is None else ZoneBase._valid_polygon(pts)


class ZoneOut(ZoneBase, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- events ----
class EventObjectOut(ORMModel):
    track_id: int
    object_class: str
    max_confidence: float
    first_seen: datetime
    last_seen: datetime
    zones: list[Any]
    trajectory: list[Any]


class NotificationOut(ORMModel):
    id: int
    event_id: int | None
    channel: str
    status: str
    detail: str | None
    created_at: datetime


class EventOut(ORMModel):
    id: int
    event_type: str
    status: str
    timestamp: datetime
    start_time: datetime
    end_time: datetime | None
    duration: float
    object_class: str | None
    confidence: float
    zone_id: int | None
    zone_name: str | None
    video_path: str | None
    snapshot_path: str | None
    video_size_bytes: int
    summary: str | None
    summary_source: str | None
    notification_status: str
    is_protected: bool
    created_at: datetime
    summary_error: str | None = None
    source: str = "live"
    analysis_id: int | None = None
    analysis_name: str | None = None
    video_offset: float | None = Field(None, description="Seconds into the uploaded video (recorded-video events)")
    video_url: str | None = None
    snapshot_url: str | None = None


class EventDetail(EventOut):
    metadata_json: dict
    objects: list[EventObjectOut]
    notifications: list[NotificationOut]


class EventPage(BaseModel):
    items: list[EventOut]
    total: int
    page: int
    page_size: int


class EventUpdate(BaseModel):
    is_protected: bool | None = None


# -------------------------------------------------------------- settings ----
class RuntimeSettings(BaseModel):
    """Runtime-editable settings persisted in the database."""

    motion_sensitivity: int = Field(..., ge=1, le=100)
    motion_min_area: int = Field(..., ge=10, le=200000)
    detection_interval: int = Field(..., ge=1, le=60)
    yolo_confidence: float = Field(..., ge=0.05, le=0.99)
    relevant_objects: list[str]
    pre_event_seconds: float = Field(..., ge=0, le=30)
    post_event_seconds: float = Field(..., ge=1, le=60)
    max_event_seconds: float = Field(..., ge=10, le=1800)
    event_cooldown_seconds: float = Field(..., ge=0, le=300)
    trigger_on_relevant_object: bool
    trigger_on_zone_entry: bool
    trigger_on_loitering: bool
    trigger_on_motion: bool
    loitering_seconds: float = Field(..., ge=1, le=3600)
    loitering_classes: list[str]
    twilio_enabled: bool = True
    telegram_enabled: bool
    email_enabled: bool
    gemini_enabled: bool
    notify_event_types: list[str]
    max_storage_gb: float = Field(..., ge=0.1, le=10000)
    retention_days: int = Field(..., ge=1, le=3650)
    auto_delete_enabled: bool


class RuntimeSettingsUpdate(BaseModel):
    motion_sensitivity: int | None = Field(None, ge=1, le=100)
    motion_min_area: int | None = Field(None, ge=10, le=200000)
    detection_interval: int | None = Field(None, ge=1, le=60)
    yolo_confidence: float | None = Field(None, ge=0.05, le=0.99)
    relevant_objects: list[str] | None = None
    pre_event_seconds: float | None = Field(None, ge=0, le=30)
    post_event_seconds: float | None = Field(None, ge=1, le=60)
    max_event_seconds: float | None = Field(None, ge=10, le=1800)
    event_cooldown_seconds: float | None = Field(None, ge=0, le=300)
    trigger_on_relevant_object: bool | None = None
    trigger_on_zone_entry: bool | None = None
    trigger_on_loitering: bool | None = None
    trigger_on_motion: bool | None = None
    loitering_seconds: float | None = Field(None, ge=1, le=3600)
    loitering_classes: list[str] | None = None
    twilio_enabled: bool | None = None
    telegram_enabled: bool | None = None
    email_enabled: bool | None = None
    gemini_enabled: bool | None = None
    notify_event_types: list[str] | None = None
    max_storage_gb: float | None = Field(None, ge=0.1, le=10000)
    retention_days: int | None = Field(None, ge=1, le=3650)
    auto_delete_enabled: bool | None = None


class RelevantObjects(BaseModel):
    relevant_objects: list[str]
    available_classes: list[str] = []


class LoiteringSettings(BaseModel):
    loitering_seconds: float = Field(..., ge=1, le=3600)
    loitering_classes: list[str]
    trigger_on_loitering: bool = True


class LoiteringRecordOut(ORMModel):
    id: int
    track_id: int
    object_class: str
    zone_id: int | None
    zone_name: str
    enter_time: datetime
    exit_time: datetime | None
    duration: float
    threshold: float
    status: str
    event_id: int | None


# --------------------------------------------------------- notifications ----
class NotificationConfigStatus(BaseModel):
    twilio_configured: bool = False
    twilio_enabled: bool = True
    twilio_to: str | None = None
    telegram_configured: bool
    telegram_enabled: bool
    email_configured: bool
    email_enabled: bool
    gemini_configured: bool
    gemini_enabled: bool
    gemini_model: str
    alert_email: str | None
    notify_event_types: list[str]


class NotificationTestRequest(BaseModel):
    channel: Literal["twilio", "telegram", "email", "all"] = "all"


class ChannelResult(BaseModel):
    channel: str
    status: str
    detail: str | None = None


# --------------------------------------------------------------- reports ----
class ReportOut(ORMModel):
    id: int
    event_id: int | None
    file_path: str
    size_bytes: int
    created_at: datetime
    download_url: str | None = None


# ------------------------------------------------------------- timelapse ----
class TimelapseRequest(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")
    speed: int = Field(4, ge=1, le=30, description="Keep 1 of every N frames")


class TimelapseOut(ORMModel):
    id: int
    date: str
    file_path: str | None
    status: str
    event_count: int
    duration: float
    size_bytes: int
    error: str | None
    created_at: datetime
    video_url: str | None = None


# ------------------------------------------------------------- analytics ----
class CountItem(BaseModel):
    label: str
    count: int


class StorageInfo(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int
    event_bytes: int
    snapshot_bytes: int
    report_bytes: int
    timelapse_bytes: int
    max_storage_bytes: int
    usage_percent: float
    retention_days: int
    auto_delete_enabled: bool


class AnalyticsSummary(BaseModel):
    events_today: int
    events_week: int
    events_total: int
    person_detections: int
    vehicle_detections: int
    zone_violations: int
    loitering_events: int
    avg_duration: float
    camera_running: bool
    storage: StorageInfo
    recent_events: list[EventOut]


class AnalyticsCharts(BaseModel):
    by_hour: list[CountItem]
    by_object: list[CountItem]
    by_type: list[CountItem]
    by_zone: list[CountItem]
    by_day: list[CountItem]


class CleanupResult(BaseModel):
    deleted_events: int
    freed_bytes: int
    reason: str


# -------------------------------------------------------- video analysis ----
class VideoAnalysisStatus(LocalTimeModel):
    analysis_id: int
    status: str
    stage: str | None
    progress: float
    frames_processed: int
    total_frames: int
    current_time: float = Field(..., description="Position in the video, seconds")
    duration: float
    events_detected: int
    objects_detected: int
    persons_detected: int
    vehicles_detected: int
    zone_violations: int
    loitering_events: int
    object_counts: dict
    detections_run: int
    processing_seconds: float
    error: str | None
    warning: str | None


class VideoAnalysisOut(VideoAnalysisStatus):
    filename: str
    original_name: str
    size_bytes: int
    width: int
    height: int
    fps: float
    codec: str | None
    recorded_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    video_url: str | None
    preview_ready: bool


class AnalysisStartResponse(BaseModel):
    analysis_id: int
    status: str
