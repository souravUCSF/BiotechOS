// Resolve the backend base URL at runtime so the app works no matter which host
// the browser used to reach the frontend (localhost, claw.local, a LAN IP, ...).
// The backend runs on port 8010 on the same host as the frontend.
export function apiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_BASE;
  if (env) return env;
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8010`;
  }
  return "http://localhost:8010";
}

export const API_BASE = apiBase();
