# AI Attendance — Backend

FastAPI service for face-based student attendance. It registers face embeddings with [InsightFace](https://github.com/deepinsight/insightface), checks liveness with [Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing), and stores student accounts and sessions on the **local filesystem** (JSON under `backend/data/`).

## Features

- Student signup, login, and bearer-token sessions
- Face registration (`POST /register-face`, authenticated)
- Attendance sessions: start, stop, and live status
- Per-student attendance marking with face match + anti-spoof checks
- Teacher listing of enrolled students (`GET /students`)

## Run the server

From the `backend/` directory (virtualenv activated):

```bash
cd backend
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000 --reload-exclude 'venv/*'
```

- Health check: [http://127.0.0.1:8000](http://127.0.0.1:8000) — must return JSON before the frontend/ngrok tunnel will work
- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

First startup can take a minute while InsightFace and anti-spoof models load.

## System requirements

| Requirement | Notes |
|-------------|--------|
| **Python** | 3.9+ (3.10+ recommended) |
| **Disk** | Space for InsightFace `buffalo_l` weights, anti-spoof models, and `data/` (student JSON files) |
| **RAM** | Several GB recommended when loading InsightFace + PyTorch anti-spoof models |
| **Camera** | Not required on the server; clients send images via HTTP |

No Redis or external database is required.

## Local data storage

All persistence lives under `backend/data/`:

| Path | Contents |
|------|----------|
| `data/students/*.json` | One file per student (email, name, password hash, face embedding) |
| `data/students_index.json` | List of enrolled emails |
| `data/sessions/*.json` | Login tokens with expiry |
| `data/kv/` | Short-lived key/value records (legacy demo routes) |

Student data is **not** committed to git (see repo `.gitignore`). Back up `backend/data/` if you need to preserve enrollments between machines.

Verify storage:

```bash
python test_local_db.py
```

## Python dependencies

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Project layout

```
backend/
├── main.py              # FastAPI app and routes
├── auth_utils.py        # Password hashing
├── student_store.py     # Filesystem-backed student CRUD
├── local_db.py          # Paths and JSON helpers
├── data/                # Local database (created at runtime)
├── requirements.txt
├── resources/
│   └── anti_spoof_models/
└── src/
```

## Setup

1. **Install dependencies** (see above).
2. **Ensure anti-spoof models exist** under `resources/anti_spoof_models/`.
3. **Run the API**

   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

   On first request, `data/` directories are created automatically.

## API overview

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health message |
| `POST` | `/register-student` | Register with name + face scans (returns `id`) |
| `POST` | `/auth/login` | Login, returns bearer token |
| `GET` | `/auth/me` | Current student (requires `Authorization: Bearer <token>`) |
| `GET` | `/students` | List students (teacher/admin use) |
| `POST` | `/register-face` | Register face embedding (authenticated) |
| `POST` | `/attendance/start` | Start attendance window |
| `POST` | `/attendance/stop` | Stop session, return marked list |
| `GET` | `/attendance/status` | Session active flag and marked students |
| `GET` | `/students/me/status` | Face registered / session / already marked |
| `POST` | `/students/me/mark-attendance` | Mark attendance with webcam image |

Legacy/demo routes (`/verify-face`, `/start-attendance`, `/attendance-session`) may still exist for older flows.

## Configuration

- **Data directory**: change `DATA_DIR` in `local_db.py` if you want a different path.
- **CORS**: local dev origins in `main.py`, plus `FRONTEND_URL` / `CORS_ORIGINS` from `.env`, and `https://*.vercel.app` via regex (for Vercel-hosted frontend). See `.env.example`.
- **Vercel + laptop backend**: expose this API with an HTTPS tunnel (ngrok / Cloudflare); set `NEXT_PUBLIC_API_URL` on Vercel. Details: [`../frontend/README.md`](../frontend/README.md#deploy-frontend-on-vercel-backend-on-your-laptop).
- **Face match thresholds**:
  - Browser face-api.js (128-d): `FACE_API_DISTANCE_THRESHOLD` (default `0.45`, euclidean distance). LMS flows accept face-api.js descriptors only.
- **Anti-spoof / location**: image-only pipelines; unchanged by browser embeddings (`ENABLE_ANTI_SPOOF`, `ENABLE_LOCATION_DETECTION`)
- **Session TTL**: `SESSION_TTL_SECONDS` (default 7 days).

## Troubleshooting

### ngrok shows `502` on `OPTIONS /auth/login` (or other routes)

That means the tunnel reached your machine but **nothing healthy is listening on port 8000** — not a CORS bug.

1. In the terminal running uvicorn, confirm you see `Application startup complete` (first boot can take ~1 minute).
2. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser; you should get `{"message":"AI Proctoring Backend Running"}`.
3. If startup failed with `No module named 'sklearn'`, run `pip install -r requirements.txt` and restart uvicorn.
4. If `--reload` crashed after `pip install`, stop uvicorn and start again with `--reload-exclude 'venv/*'` (see command above).
5. Only one process should bind port 8000 (`lsof -i :8000`).

For **local** `npm run dev` only, you can point `NEXT_PUBLIC_API_URL` at `http://127.0.0.1:8000` in `.env.development.local` and skip ngrok.

## Related

- Frontend: [`../frontend/README.md`](../frontend/README.md)
