/** Uvicorn bind address — not valid as a browser request target. */
function normalizeApiUrl(url: string): string {
  try {
    const parsed = new URL(url);
    if (parsed.hostname === "0.0.0.0") {
      parsed.hostname = "127.0.0.1";
      return parsed.toString().replace(/\/$/, "");
    }
  } catch {
    /* fall through */
  }
  return url;
}

/** Private / LAN hosts — not reachable from browsers loading the Vercel app. */
export function isPrivateApiHost(hostname: string): boolean {
  if (hostname === "localhost") return true;
  if (/^127\./.test(hostname)) return true;
  if (/^10\./.test(hostname)) return true;
  if (/^192\.168\./.test(hostname)) return true;
  const match = /^172\.(\d+)\./.exec(hostname);
  if (match) {
    const second = Number(match[1]);
    if (second >= 16 && second <= 31) return true;
  }
  return false;
}

/**
 * - Local `next dev`: `.env.development.local` → LAN IP (see `.env.example`)
 * - Vercel: Project env `NEXT_PUBLIC_API_URL` → public HTTPS tunnel only
 */
/**
 * Base URL for all backend API calls. Set `NEXT_PUBLIC_API_URL` in env
 * (e.g. `.env.local` for dev, Vercel env vars or `.env.production` for deploy).
 */
export function getApiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (!raw) {
    if (process.env.NODE_ENV === "production") {
      return "";
    }
    return "http://127.0.0.1:8000";
  }

  const configured = normalizeApiUrl(raw.replace(/\/$/, ""));

  try {
    const { hostname } = new URL(configured);
    if (process.env.VERCEL === "1" && isPrivateApiHost(hostname)) {
      throw new Error(
        `NEXT_PUBLIC_API_URL (${configured}) uses a private/LAN host. ` +
          "On Vercel, set a public HTTPS tunnel URL (ngrok, Cloudflare Tunnel, etc.).",
      );
    }
  } catch (error) {
    if (error instanceof Error && error.message.includes("private/LAN")) {
      throw error;
    }
    throw new Error(`Invalid NEXT_PUBLIC_API_URL: ${raw}`);
  }

  return configured;
}
