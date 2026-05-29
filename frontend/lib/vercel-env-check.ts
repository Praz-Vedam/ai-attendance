import { isPrivateApiHost } from "./api-base-url";

/** Fail Vercel builds when API URL is missing or still points at a LAN address. */
export function assertVercelApiEnv(): void {
  if (process.env.VERCEL !== "1") return;

  const url = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (!url) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is required on Vercel. " +
        "Set it to your public HTTPS tunnel (ngrok / Cloudflare Tunnel) → laptop :8000.",
    );
  }

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(`NEXT_PUBLIC_API_URL is not a valid URL: ${url}`);
  }

  if (parsed.protocol !== "https:") {
    throw new Error(
      "NEXT_PUBLIC_API_URL on Vercel must use https:// (browsers block http from https pages).",
    );
  }

  if (isPrivateApiHost(parsed.hostname)) {
    throw new Error(
      `NEXT_PUBLIC_API_URL (${url}) cannot be a LAN/private address on Vercel. ` +
        "Use a public HTTPS tunnel URL instead.",
    );
  }
}
