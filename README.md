# FBV1

FBV1 is a desktop-first multi-platform profile console.

## Layout

- `backend/`: FastAPI backend package
- `Fbv1.py`: primary desktop launcher
- `Fbv2.py`: compatibility launcher that forwards to `Fbv1.py`
- `fbv1_app/`: Tk desktop app package

## Backend Structure

- `backend/api/`: REST routes and WebSocket events
- `backend/core/`: settings, logging, executor, and event broker
- `backend/modules/`: job handlers
- `backend/data/`: SQLAlchemy models, repository helpers, SQLite storage
- `backend/workers/`: queue submission and threaded execution

## Backend Entry Points

- `run_backend.py`
- `backend/main.py`

## Backend Features

- FastAPI routes for health, jobs, and profiles
- ThreadPoolExecutor task runner
- WebSocket event stream at `/api/events`
- SQLite-backed profile/job state
- generic checker jobs for approved endpoints you control
- bulk queue controls:
  - `POST /api/jobs/start-all`
  - `POST /api/jobs/stop-all`

## API Endpoints

- `GET /api/health`
- `GET /api/jobs`
- `POST /api/jobs`
- `POST /api/jobs/start-all`
- `POST /api/jobs/stop-all`
- `GET /api/jobs/{job_id}`
- `GET /api/profiles`
- `POST /api/profiles`
- `WS /api/events`

## Checker Jobs

The checker job remains generic and compliant. It classifies approved endpoint responses into:

- `live`
- `review`
- `failed`
- `unknown`

Example payload:

```json
{
  "job_type": "checker",
  "profile_id": "<profile-id>",
  "payload": {
    "target_url": "https://example.com/health",
    "method": "GET",
    "live_status_codes": [200],
    "review_status_codes": [401, 403],
    "failed_status_codes": [404, 500, 503],
    "review_keywords": ["verification required"],
    "failure_keywords": ["disabled", "blocked"]
  }
}
```

Profiles persist:

- `health_status`: `unknown`, `live`, `review`, or `failed`
- `health_reason`
- `last_checked_at`

## Run

Desktop:

```bash
python Fbv1.py
```

Backend only:

```bash
python run_backend.py
```
