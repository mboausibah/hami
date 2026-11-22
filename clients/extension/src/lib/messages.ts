import type { HamiAlert, HostLookup, ScanResult, SourceType, Watch } from "@hami/shared";

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
  | { type: "autoCheck"; url: string };

export type Response<T> = { ok: true; data: T } | { ok: false; error: string; status?: number };

export interface AlertsData {
  alerts: HamiAlert[];
  unseen: number[];
  watches: Watch[];
}

export type ScanData = ScanResult;
export type LookupData = Record<string, HostLookup>;

export function send<T>(req: Request): Promise<Response<T>> {
  return chrome.runtime.sendMessage(req) as Promise<Response<T>>;
}
