# PreVuCam — AI-Enhanced Event-Driven Surveillance System

PreVuCam watches a camera, ignores everything that doesn't matter, and when something relevant happens it saves **one MP4 that starts 7 seconds before the event and ends 7 seconds after it**, together with a snapshot, structured metadata, an AI-written summary, Telegram/email alerts and an optional PDF incident report.

Nothing is recorded continuously: the last few seconds live only in a bounded in-memory ring buffer until an event needs them.

---

## Features

| Area | What it does |
|---|---|
| Camera | **Your computer's webcam via the browser** (Live Monitoring → Start), server-side USB webcam, RTSP/IP camera, video file (test mode), Raspberry Pi camera (picamera2). Start/stop/restart, auto-reconnect, MJPEG live stream. |
| Motion gate | OpenCV running-average background subtraction. YOLO only runs while there is motion, live tracks, or an active event. |
| Detection | YOLOv8n (Ultralytics), all 80 COCO classes, configurable confidence, input size and detection interval. |
| Relevant objects | User-selected classes create events; others are drawn grey and ignored (`dog` ≠ event, `person` = event). |
| Tracking | Dependency-free IoU + centroid tracker gives stable IDs across frames (used for zones, loitering, trajectories). |
| Smart zones | Polygons/rectangles drawn on the live frame, stored normalised (resolution independent). Ground-anchor (bottom-centre of the box) membership. |
| Loitering | Per-(track, zone) dwell timer with a global or per-zone threshold; every stay is persisted with enter/exit/duration/status. |
| Pre/post recording | 7 s circular buffer (JPEG-compressed, hard capacity) + live frames + 7 s post window, written through a single timestamp-synchronised writer → one H.264 MP4. |
| Event engine | Start / extend / upgrade (`object_detection` → `zone_violation` → `loitering`), cooldown, max length, snapshot, metadata, trajectories. |
| Search | Date, time range, duration range, object, zone, type, status, keyword (summary/zone/object). |
| Gemini | Summarises finished events from structured metadata + one snapshot. Never sees the live stream. Falls back to a deterministic template summary. |
| Alerts | **Twilio SMS / WhatsApp** (one message per finalised event), plus optional Telegram and SMTP email. Channels are isolated: one failing never blocks the others, the summary or the video. |
| PDF reports | ReportLab incident report with details, snapshot, AI description, tracked objects and evidence path. |
| Timelapse | Concatenates a day's event clips chronologically with speed-up, title cards and timestamps. |
| Storage | Disk/quota monitoring, retention by age + quota, manual or hourly auto-cleanup; *protected* events are never auto-deleted. |
| Dashboard | Dark CCTV-style React app: live view with overlays, KPI cards, charts, event feed, event details, zone editor, settings. |
| Recorded video analysis | Upload .mp4/.avi/.mov/.mkv/.webm and run the **same** detection engine on it in the background: progress, cancel, 7 s pre/post clips on the video's own timeline, timeline view, events in the normal Events/Dashboard/Reports. |

---

## Architecture

```
React (Vite) dashboard ──REST (axios)──▶ FastAPI routers (app/api/routes)
        ▲                                   │  Pydantic schemas, DI, validation
        └──── WebSocket /ws/live ◀──┐       ▼
             (status + live events  │   Service layer (app/services)
              only)                 │       │
                                    └── EventBus ◀── SurveillancePipeline (capture thread)
                                                     camera → motion → YOLO → tracker → zones
                                                     → loitering → relevant filter → EventManager
                                                     → CircularFrameBuffer / EventRecorder
                                                            │ worker pool: H.264, summary, alerts
                                                            ▼
                                              SQLAlchemy (SQLite / PostgreSQL) + storage/
```

* **Frontend and backend are separate apps.** The UI talks to the backend only through `/api` REST endpoints; the WebSocket is used solely for push updates (camera status, detections, event started/completed).
* **Route files contain no business logic** – they validate input and call services.
* **The capture loop never blocks on I/O-heavy work**: transcoding, Gemini, Telegram and email run on a worker pool after the clip is closed.
* **One detection engine, two input modes.** `services/detection_engine.py` holds the whole per-frame pipeline. `pipeline.py` feeds it from the live `CameraService`; `video_analysis_service.py` feeds it from an uploaded file. Nothing is duplicated.

```
                 DetectionEngine (motion → YOLO → relevant filter → tracking → zones/loitering → EventManager)
                        ▲                                   ▲
   Live camera  ── CameraService (wall clock)      Uploaded video ── VideoAnalysis runner (media time = frame / fps)
```

### Event flow

```
frame ─▶ motion? ─▶ YOLO (every N frames) ─▶ tracker IDs ─▶ zone membership ─▶ dwell timers
                                                        │
              relevant object / zone entry / loitering ─┴─▶ EventManager.trigger()
first trigger:   pull ≤7 s from ring buffer ─▶ open recorder ─▶ snapshot ─▶ DB row (status=recording)
more triggers:   extend; upgrade type if higher priority
no trigger 7 s:  close recorder ─▶ H.264 MP4 ─▶ metadata/objects ─▶ summary (Gemini|template)
                 ─▶ Telegram ─▶ email ─▶ status=completed ─▶ WebSocket "event_completed"
```

---

## Live Monitoring with your webcam

1. Open **Live Monitoring** and press **Start**. The browser asks for camera permission (`navigator.mediaDevices.getUserMedia`).
2. Your real webcam appears; the browser sends frames (640×480, centre-cropped to 4:3, up to 15 fps) over the WebSocket `/ws/webcam`. The backend runs each one through the **same `DetectionEngine` as Video Analysis**: motion gate → YOLOv8n → relevant-object filter → tracking → zones → loitering → event manager with the 7 s ring buffer → one MP4 per event → snapshot → Gemini summary → Twilio.
3. Each reply carries that frame's real tracks, which are drawn over the local video (box, class, confidence, tracking ID, dwell), plus motion state and FPS. The Pipeline panel shows *Webcam · device name*, *Streaming*, processed/sent FPS, *Motion: Detected / No motion*, detector state and the active event.
4. **Stop** releases the webcam and stops the backend pipeline (an open event is finalised). **Restart** = stop + start. Monitoring keeps running while you switch pages inside the app; closing or reloading the tab stops it after 3 s.

Messages: *“Camera permission denied. Please allow camera access in your browser settings.”*, *“No webcam detected.”*, or that the webcam is in use by another app. There is no simulated fallback. Camera access needs `http://localhost` or HTTPS: from another PC on the LAN use HTTPS or the server-side `webcam`/`rtsp` sources (Camera page).

The pre-event buffer can only contain footage captured since you pressed Start: an object appearing 3 s after Start gets ~3 s of pre-event context, after that the full 7 s.

## API credentials (Gemini, Twilio)

Enter them in **`backend/config/api_keys.py`** (created with placeholders; listed in `.gitignore`, template in `api_keys.example.py`), then restart the backend:

```python
GEMINI_API_KEY = "AIza..."
TWILIO_ACCOUNT_SID = "AC..."
TWILIO_AUTH_TOKEN = "..."
TWILIO_FROM_NUMBER = "+14155550100"      # your Twilio number, or "whatsapp:+14155238886" for the WhatsApp sandbox
TWILIO_TO_NUMBER = "+919800000000"       # your phone (E.164), or "whatsapp:+91..."
```

Values there override `.env`. Empty values or the `PASTE_YOUR_..._HERE` placeholders mean “not configured”: events are still detected, recorded and stored; the summary falls back to a rule-based description (UI: *AI summary unavailable*) and Twilio is skipped (logged, shown as *skipped* in Notifications). Keys are only used by the backend – never sent to the browser, stored in the database or logged. A Twilio trial account can only text numbers you have verified in the Twilio console. SMS cannot carry the local snapshot (Twilio needs a public URL); the alert text includes event type, object, zone, confidence, time, duration and the summary. Choose which event types send alerts under **Notifications → Alert on event types**.

## Recorded video analysis

1. **Video Analysis** (sidebar → Monitor) → drag a file in or **Choose Video** → **Upload**. The server validates type and size, stores it under `storage/uploads/` with a safe unique name and extracts duration, resolution, FPS and frame count.
2. *(Optional)* **Zones** → pick *Video: your_file* as the background → draw zones on a real frame of that video.
3. **Start Analysis**. Processing runs in the background (one video at a time) and the page shows %, frames, current timestamp, events, objects, zone violations and loitering. **Cancel** stops cleanly: the decoder is released, any half-recorded event is closed and saved, status becomes `cancelled`.
4. When done you get the summary cards, the original video (a browser-playable preview is generated automatically for .avi/.mkv/mp4v files), a clickable event timeline and the event list with View / Play / Download / PDF.

How it maps to the live pipeline:

* Frames are decoded one at a time with OpenCV – never the whole file in RAM. Large videos are downscaled to `ANALYSIS_MAX_WIDTH` (1280 px) for processing and clips.
* Each frame gets **media time** `t = frame_index / fps`. The 7 s ring buffer, the event duration and the 7 s post window are all measured on that timeline, so a clip is exactly *previous 7 s + event + next 7 s* of the source video however fast the PC processes it.
* The YOLO interval is scaled to the video's FPS so detection happens at the same rate per second as live (a 30 fps video runs YOLO on ~1 in 6 frames, and only while there is motion, a tracked object or an open event).
* Relevant objects, zones, loitering thresholds, triggers, Gemini and Telegram/email settings are the same ones used live.
* Events are stored in the normal `events` table with `source = video`, `analysis_id` and `video_offset` (seconds into the video). The Events page can filter by *Source* and *Analysis / video*; the keyword search also matches the file name. Dashboard counters, PDF reports and alerts include them automatically.
* Event wall-clock times are *upload start time + position in the video* unless you pass `recorded_at` (the real time of frame 0) to the upload API.
* If Gemini is not configured or fails, the event is still saved and the UI shows **“AI summary unavailable.”** together with a rule-based description and the reason.

Test video: `samples/security_test.mp4` (1280×720, 30 fps, 92 s; regenerate with `python backend/scripts/make_security_test_video.py`). With a zone over the right half it produces exactly three events: a person (00:08), a bus entering the zone (00:26) and a person loitering in the zone (00:49).

API: `POST /api/video-analysis/upload` · `POST /{id}/start[?force=true]` · `GET /{id}` · `GET /{id}/status` · `POST /{id}/cancel` · `GET /{id}/events` · `GET /{id}/video` · `GET /{id}/frame?t=` · `DELETE /{id}[?delete_events=true]` · `GET /api/video-analysis`.

---

## Folder structure

```
prevucam/
├── backend/
│   ├── app/
│   │   ├── main.py                 # app factory: routers, CORS, middleware, lifespan
│   │   ├── api/deps.py
│   │   ├── api/routes/             # camera, events, detection(+loitering), zones, settings,
│   │   │                           # reports, notifications, analytics(+storage), timelapse, live(ws)
│   │   ├── core/config.py          # ALL configuration (env/.env)
│   │   ├── core/security.py        # optional API key
│   │   ├── database/               # engine/session, models, Pydantic schemas
│   │   ├── services/               # camera_service, motion_detector, object_detector, tracker,
│   │   │                           # circular_buffer, video_recorder, event_manager, zone_detector,
│   │   │                           # loitering_detector, pipeline, summarizer, telegram_service,
│   │   │                           # email_service, notification_service, report_service,
│   │   │                           # timelapse_service, storage_service, analytics_service, ...
│   │   ├── utils/                  # video_utils (ffmpeg), image_utils (overlays), logger
│   │   └── tests/                  # 50 tests (unit, API, integration, real-YOLO end-to-end)
│   ├── scripts/make_sample_video.py
│   ├── requirements.txt  .env.example  Dockerfile  pytest.ini
├── frontend/
│   ├── src/{components,pages,services/api.js,hooks,context,utils}
│   ├── package.json  vite.config.js  .env.example  Dockerfile  nginx.conf
├── storage/{events,snapshots,reports,timelapse,uploads,logs}/
├── models/yolov8n.pt
├── docker-compose.yml  .gitignore  README.md
```

---

## Installation

Requirements: Python 3.10+, Node 18+, FFmpeg (recommended – produces browser-playable H.264; without it clips are saved as MPEG-4 Part 2, which some browsers won't play inline).

### Backend

Python **3.10 or newer** is required (3.11/3.12 recommended).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # Windows: copy .env.example .env
python run.py                                            # checks the environment, then starts on :8000
```

`run.py` prints a plain error (wrong Python version, missing package, import failure) instead of a stack trace. `uvicorn app.main:app --port 8000` still works if you prefer.

**Windows (PowerShell), step by step**

```powershell
cd "C:\path\to\prevucam\backend"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env
python run.py
```
Keep this window open and start the frontend in a second window. FFmpeg does not need to be installed separately: `imageio-ffmpeg` (in requirements) ships a binary that is used automatically for browser-playable clips. If the project lives in OneDrive, right-click the folder → **Always keep on this device**.

* API docs: <http://localhost:8000/docs> (Swagger) and <http://localhost:8000/redoc>
* The database (`storage/prevucam.db`) and tables are created automatically on first start.
* If `models/yolov8n.pt` is missing it is downloaded automatically on first use.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env        # optional
npm run dev                 # http://localhost:5173  (proxies /api, /media, /ws to :8000)
```

Production build: `npm run build` → static files in `frontend/dist` (see `frontend/nginx.conf`).

### Docker

```bash
docker compose up --build   # dashboard http://localhost:8080 · API http://localhost:8000/docs
```

---

## Environment variables

All settings live in `backend/.env` (template: `backend/.env.example`). Thresholds such as motion sensitivity, confidence, relevant objects, pre/post seconds and loitering time are **defaults** – once changed in the UI they are persisted in the `settings` table.

| Variable | Default | Meaning |
|---|---|---|
| `CAMERA_SOURCE_TYPE` / `CAMERA_SOURCE` | `browser` / `0` | browser · webcam · rtsp · file · picamera |
| `CAMERA_WIDTH/HEIGHT/FPS` | 640/480/15 | processing & recording resolution |
| `CAMERA_AUTOSTART` | false | start the camera on boot |
| `PRE_EVENT_SECONDS` / `POST_EVENT_SECONDS` | 7 / 7 | ring buffer length / post window |
| `MOTION_SENSITIVITY` / `MOTION_MIN_AREA` | 60 / 800 | motion gate |
| `YOLO_CONFIDENCE` / `YOLO_IMGSZ` / `DETECTION_INTERVAL` | 0.5 / 416 / 3 | detector |
| `RELEVANT_OBJECTS` | person,car,motorcycle,bicycle,bus,truck | default event classes |
| `LOITERING_SECONDS` | 20 | global dwell threshold |
| `DATABASE_URL` | SQLite in `storage/` | e.g. `postgresql+psycopg://user:pw@host/db` |
| `STORAGE_PATH` / `MODEL_PATH` | `../storage` / `../models/yolov8n.pt` | relative to `backend/` |
| `MAX_STORAGE_GB` / `RETENTION_DAYS` / `AUTO_DELETE_ENABLED` | 10 / 30 / false | retention |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | – / `gemini-2.5-flash` | AI summaries |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | – | Telegram alerts |
| `SMTP_HOST/PORT/USERNAME/PASSWORD`, `SMTP_USE_SSL`, `SMTP_FROM`, `ALERT_EMAIL` | – | email alerts |
| `API_KEY` | – | if set, `/api` and `/media` require `X-API-Key` (or `?api_key=`) |

Secrets are never hard-coded, stored in the database or returned by the API (the notification status endpoint only reports *configured: yes/no*).

**Database setup:** nothing to do for SQLite. For PostgreSQL install `psycopg[binary]`, create an empty database and set `DATABASE_URL`; tables are created on start.

---

## Running

### Test mode (no camera needed)

1. Generate the sample clip (a pedestrian walks into the right half of the scene, stands ~26 s, leaves):
   ```bash
   cd backend && python scripts/make_sample_video.py      # -> storage/uploads/sample_walkin.mp4
   ```
2. Open the dashboard → **Zones** → *Draw rectangle* over the right half → name it `Restricted Area` → Save.
3. **Camera** → *Test videos* → **Use** on `sample_walkin.mp4` (turn *Loop video* off first if you want a single pass).
4. Watch **Live Monitoring**: the track turns green (relevant) → amber (zone) → red (loitering after 20 s).
5. ~7 s after the person leaves, the event appears under **Events** with its 7 s + event + 7 s clip, summary and timeline. Generate the PDF from the event page, then build the **Timelapse** for today.

You can also upload any MP4 from the Camera page, or analyse a recorded video under **Video Analysis**.

### Webcam

Set `CAMERA_SOURCE_TYPE=webcam`, `CAMERA_SOURCE=0` (or choose it on the Camera page) and press **Start camera**.

### RTSP / IP camera

`CAMERA_SOURCE_TYPE=rtsp`, `CAMERA_SOURCE=rtsp://user:pass@192.168.1.20:554/stream1`. The camera reconnects automatically if the stream drops.

### Raspberry Pi

The Pi-specific code is isolated in `PiCameraSource` (`backend/app/services/camera_service.py`); everything else is identical on a PC.

```bash
sudo apt install -y python3-picamera2 ffmpeg     # Raspberry Pi OS (Bookworm)
python -m venv --system-site-packages .venv      # so picamera2 is visible inside the venv
pip install -r requirements.txt
```
Recommended `.env` for a Pi 4/5: `CAMERA_SOURCE_TYPE=picamera`, `CAMERA_FPS=10`, `YOLO_IMGSZ=320`, `DETECTION_INTERVAL=4`, `CAMERA_AUTOSTART=true`. A USB webcam works too (`webcam`). The motion gate keeps YOLO idle when the scene is static, and the ring buffer is JPEG-compressed (≈3 MB for 7 s).

---

## API overview

Full interactive documentation with request/response schemas and error codes is at `/docs`.

| Method & path | Purpose |
|---|---|
| `GET /api/camera/status` · `POST /api/camera/start|stop|restart` | camera control (`start` body: `source_type`, `source`, `loop`) |
| `GET /api/camera/stream?overlay=true` · `GET /api/camera/snapshot` | MJPEG live view / single frame |
| `POST /api/camera/upload` · `GET/DELETE /api/camera/uploads` | test videos |
| `GET /api/events` | search: `date, start_time, end_time, date_from, date_to, object_class, keyword, zone, event_type, min_duration, max_duration, status, page, page_size` |
| `GET/PATCH/DELETE /api/events/{id}` | details (objects, trajectory, notifications) / protect / delete |
| `GET /api/events/{id}/video` · `/snapshot` | downloads |
| `POST /api/events/{id}/summary` · `/notify` | regenerate AI summary / send alerts now |
| `GET/POST /api/zones` · `GET/PUT/DELETE /api/zones/{id}` | smart zones |
| `GET/PUT /api/settings` · `POST /api/settings/reset` | runtime settings |
| `GET/PUT /api/settings/relevant-objects` | relevant classes |
| `GET/PUT /api/loitering/settings` · `GET /api/loitering/active` · `/records` | loitering |
| `GET /api/detection/live|classes|model` · `POST /api/detection/model/reload` | detector |
| `POST /api/reports/events/{id}` · `GET /api/reports` · `GET/DELETE /api/reports/{id}` | PDF reports |
| `POST /api/timelapse/generate` · `GET /api/timelapse[/{id}]` · `/{id}/download` | timelapse |
| `GET /api/notifications/status` · `POST /api/notifications/test` · `GET /api/notifications` | alerts |
| `GET /api/analytics/summary|charts` · `GET /api/storage` · `POST /api/storage/cleanup` | dashboard data |
| `WS /ws/live` | `camera_status`, `detections`, `event_started`, `event_updated`, `event_completed` |

---

## Testing

```bash
cd backend
python scripts/make_sample_video.py   # enables the real-YOLO end-to-end tests
pytest
```

78 tests cover the browser-webcam path (/ws/webcam frames → tracking IDs → zone event with pre-event frames, no simulated source), Twilio (one message per event, failure isolation, no secrets in errors/status), `api_keys.py` loading, video analysis (upload validation, exact 7 s pre/post context on the video timeline, merging, relevant-object filtering, zones/loitering, cancel, re-run, once-per-event alerts, API, restart recovery, real YOLO on `samples/security_test.mp4`) plus motion detection, the circular buffer (time window, hard capacity, memory bound), tracking, relevant-object filtering, zones, loitering (threshold, per-zone override, exit), the recorder (single continuous file, real-time padding), the event manager (7 + event + 7, extension, max length, upgrade, cooldown), REST APIs and validation, search filters, PDF generation, Gemini success/failure fallback, notification failure isolation, and two integration tests:

* `test_integration_motion_object_event_recording_metadata_notification` – motion → object → event → recording → metadata → summary → notification (deterministic fake detector).
* `test_full_pipeline_with_real_yolo` – the real YOLOv8n model on the sample video produces exactly one loitering event in the zone with a ~50 s clip (7 s pre + event + 7 s post).

Tests run against a temporary storage folder and database, with all secrets blanked, so they never send real alerts.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Event video won't play in the browser | Install FFmpeg (clips are transcoded to H.264). Check the log for `ffmpeg transcode failed`. |
| “Detector unavailable” badge | `models/yolov8n.pt` missing and no internet for auto-download, or `ultralytics`/`torch` not installed. Detection settings → *Retry loading model*. |
| `Unable to open video source` | Wrong webcam index / RTSP URL, or the device is in use. The camera retries every 3 s; see Camera → Status. |
| No events although objects are visible | Is the class selected under *Relevant objects*? Is the confidence threshold too high? Are triggers enabled? |
| Events end too early / never end | Adjust *Post-event recording* and *Maximum event length*. |
| Dashboard says “API offline” / “PreVuCam API not reachable” | The backend is not running on :8000 (or crashed at start-up). Start it with `python run.py` in `backend/` and read its output. In dev, the Vite proxy now answers **502 “PreVuCam API not reachable at …”** instead of a bare *500*. |
| Uploaded video won't play in the result page | The browser preview is encoded right after upload (a few seconds); the player reloads automatically. Use *Download original* meanwhile. |
| “Unable to process this video because the file is corrupted…” | The file has no decodable frames (truncated download, unsupported codec). Re-export it as H.264 MP4. |
| Analysis finds no events | Check *Relevant objects* (Detection), the YOLO confidence, and that the zone was drawn over the right area (use *Video: …* as the Zones background). |
| Alerts not delivered | Notifications page shows configured/enabled state; *Send test* reports the exact error from Telegram/SMTP. Gmail needs an App Password. |
| Gemini summary shows “Template” | `GEMINI_API_KEY` missing, Gemini disabled, or the request failed (logged as a warning). Check `GEMINI_MODEL` is a model available to your key. |
| Pi too slow | Lower `CAMERA_FPS`, set `YOLO_IMGSZ=320`, raise `DETECTION_INTERVAL`. |

Logs: console and `storage/logs/prevucam.log` (rotating) record camera start/stop, motion, detections, event creation, recording start/completion, Gemini requests, Telegram/email results and errors.

Times are stored in the server's local time and sent to the browser with its UTC offset.
