/** Default server URL. Phase 1: local `make run`. Phase 2 sets the hosted HTTPS URL here. */
export const DEFAULT_API_BASE = "http://localhost:8000";

/** How often clients refresh the reviewer-approved high-risk list and alerts (minutes). */
export const SYNC_INTERVAL_MIN = 30;

export function normalizeBaseUrl(url: string): string {
  const trimmed = url.trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(trimmed)) throw new Error("Server URL must start with http:// or https://");
  return trimmed;
}
