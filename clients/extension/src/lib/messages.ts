import type { HamiAlert, HostLookup, ScanResult, SourceType, Watch } from "@hami/shared";
import type { Classification } from "./prefilter";

/** A resource the page loaded, already sanitized on the device: no query string, no fragment, no headers,
 * no cookies, no bodies. */
export interface SnapshotResource {
  url: string;
  type: string;            // script | css | img | font | xmlhttprequest | fetch | websocket | other ...
  status: number | null;
  duration_ms: number | null;
  size: number | null;
}

export interface SnapshotPayload {
  page_url: string;        // origin + path only
  resources: SnapshotResource[];
  visible_text: string;    // capped, redacted on the device
  lang: string;
}

/** Messages from popup / pages / content scripts to the background service worker. */
export type Request =
  | { type: "scan"; url: string; sourceType?: SourceType; listingName?: string | null; force?: boolean }
  | { type: "getScan"; scanId: number; key: string }
  | { type: "lookup"; hosts: string[] }
  | { type: "watch"; scanId: number; key: string; host: string }
  | { type: "unwatch"; scanId: number }
  | { type: "alerts" }
  | { type: "markAlertsSeen" }
  | { type: "syncNow" }
  | { type: "openResult"; scanId: number; key: string }
  | { type: "classify"; url: string; resourceNames?: string[] }
  | { type: "autoCheck"; url: string; reasons: string[] }
  | { type: "consent"; agree: boolean }
  | { type: "snapshot"; payload: SnapshotPayload };

export type Response<T> = { ok: true; data: T } | { ok: false; error: string; status?: number };

export interface AlertsData {
  alerts: HamiAlert[];
  unseen: number[];
  watches: Watch[];
}

export type ScanData = ScanResult;
export type LookupData = Record<string, HostLookup>;
export type ClassifyData = Classification;

export function send<T>(req: Request): Promise<Response<T>> {
  return chrome.runtime.sendMessage(req) as Promise<Response<T>>;
}
