# AI Attendance — Frontend

Next.js web app for administrators and students: control attendance sessions, register faces via webcam, and mark attendance against the FastAPI backend.

## Features

- **Home** (`/`): legacy face register / verify demo against the API
- **Admin** (`/admin`): start and stop attendance sessions, poll live status
- **Student** (`/student/[id]`): register face and mark attendance for a given student id (email)

Uses `react-webcam` for capture and `@mediapipe/face_mesh` where face mesh helpers are needed.

## System requirements

| Requirement | Version |
|-------------|---------|
| **Node.js** | 20.x or later (LTS recommended) |
| **npm** | 10+ (comes with Node) |
| **Browser** | Modern Chromium, Firefox, or Safari with webcam permission |

The backend must be running before student or admin flows that call the API (default [http://127.0.0.1:8000](http://127.0.0.1:8000)):

```bash
cd backend
source venv/bin/activate   # Windows: venv\Scripts\activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Full backend setup (Redis, Python deps): [`../backend/README.md`](../backend/README.md).

## Dependencies

Install from `package.json`:

```bash
cd frontend
npm install
```

### Runtime (`dependencies`)

| Package | Version (approx.) | Purpose |
|---------|-------------------|---------|
| `next` | 16.x | App framework and routing |
| `react`, `react-dom` | 19.x | UI |
| `axios` | ^1.16 | HTTP client to the backend |
| `react-webcam` | ^7.2 | Webcam capture |
| `@mediapipe/face_mesh` | ^0.4 | Face mesh (client-side) |
| `@mediapipe/camera_utils` | ^0.3 | MediaPipe camera helpers |
| `@mediapipe/drawing_utils` | ^0.3 | MediaPipe drawing helpers |

### Development (`devDependencies`)

| Package | Purpose |
|---------|---------|
| `typescript` | Type checking |
| `@types/node`, `@types/react`, `@types/react-dom` | Type definitions |
| `tailwindcss`, `@tailwindcss/postcss` | Styling |
| `eslint`, `eslint-config-next` | Linting |

Exact versions are pinned in `package.json`.

## Environment variables

| Environment | File / setting | `NEXT_PUBLIC_API_URL` |
|-------------|----------------|------------------------|
| **Local dev** | `frontend/.env.development.local` | `http://192.168.20.54:8000` (your LAN IP) |
| **Vercel / production** | `frontend/.env.production` | `https://blubber-dress-startle.ngrok-free.dev` |

Copy `.env.example` → `.env.development.local` for local dev. That file is **not** used on Vercel.

`lib/api-base-url.ts` blocks private/LAN URLs when `VERCEL=1`. The Vercel build fails early if `NEXT_PUBLIC_API_URL` is missing or still a LAN address.

## Deploy frontend on Vercel (backend on your laptop)

The browser calls your API directly. Vercel cannot reach `127.0.0.1` or `192.168.x.x` on your laptop—you need a **public HTTPS tunnel** to port `8000` while the backend runs locally.

### 1. Run the backend on your laptop

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Optional `backend/.env` (see `.env.example`):

```env
FRONTEND_URL=https://your-app.vercel.app
```

CORS already allows `https://*.vercel.app` and your `FRONTEND_URL`.

### 2. Expose port 8000 with HTTPS (pick one)

**ngrok**

```bash
ngrok http 8000
```

Use the `https://….ngrok-free.app` URL as your API base.

**Cloudflare Tunnel** — point a tunnel at `http://localhost:8000` and use the issued `https://` hostname.

> Browsers block HTTPS Vercel pages from calling plain `http://` APIs (mixed content). The tunnel must be **HTTPS**.

### 3. Configure Vercel

In the Vercel project (root directory: **`frontend`**):

1. **Settings → Environment Variables**
   - `NEXT_PUBLIC_API_URL` = `https://your-tunnel.example.com` (no trailing slash)
   - Apply to **Production** and **Preview**
2. Redeploy after changing env vars (they are baked in at build time).

### 4. Deploy

```bash
cd frontend
npx vercel
```

Or connect the GitHub repo in the Vercel dashboard with **Root Directory** = `frontend`.

### Checklist

- [ ] Backend running on laptop (`uvicorn … --host 0.0.0.0 --port 8000`)
- [ ] Tunnel active and HTTPS URL opens `/` or `/docs`
- [ ] `NEXT_PUBLIC_API_URL` set on Vercel
- [ ] `FRONTEND_URL` in backend `.env` matches your Vercel URL (optional; regex covers `*.vercel.app`)
- [ ] Laptop awake and tunnel running during demos

## Setup & run

1. Install dependencies:

   ```bash
   npm install
   ```

2. Start the development server:

   ```bash
   npm run dev
   ```

3. Open [http://localhost:3000](http://localhost:3000).

### Other scripts

| Script | Command | Description |
|--------|---------|-------------|
| `dev` | `npm run dev` | Development server with hot reload |
| `build` | `npm run build` | Production build |
| `start` | `npm run start` | Serve production build |
| `lint` | `npm run lint` | Run ESLint |

Production:

```bash
npm run build
npm run start
```

## Project layout

```
frontend/
├── app/
│   ├── page.tsx              # Home / demo
│   ├── admin/page.tsx        # Attendance session control
│   ├── student/[id]/page.tsx # Student register & mark
│   ├── layout.tsx
│   └── globals.css
├── lib/
│   └── api.ts                # Axios client and API helpers
└── package.json
```

## API client

Shared helpers live in `lib/api.ts`:

- `startAttendance` / `stopAttendance` / `getAttendanceStatus`
- `registerFace`, `markAttendance`, `getStudentStatus`

Ensure route paths match the current backend (see [`../backend/README.md`](../backend/README.md)).

## Related

- Backend setup and Python requirements: [`../backend/README.md`](../backend/README.md).
