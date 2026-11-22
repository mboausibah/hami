import { DEFAULT_API_BASE, defaultLang, ensureDeviceId, type Lang } from "@hami/shared";
import type { Lists } from "./prefilter";

export interface Settings {
  serverUrl: string;
  lang: Lang;
  /** Send result hostnames (only) to POST /lookup/hosts on Google Search. Off by default. */
  checkSearchResults: boolean;
  /** Use the on-device reviewer-confirmed high-risk list (no server call). On by default. */
  localList: boolean;
  /** Automatic checking of candidate pages. Only on after the user agreed on the consent screen. */
  autoCheck: boolean;
  /** ISO time the user agreed to automatic checking (null = never asked / declined). */
  consentAt: string | null;
  /** Idle snapshots of candidate pages (resource URLs without query strings + visible text). Part of auto-check. */
  idleSnapshots: boolean;
  /** Investigator mode: full HAR of the current tab via chrome.debugger. Off by default. */
  investigatorMode: boolean;
}

export const DEFAULTS: Settings = {
  serverUrl: DEFAULT_API_BASE,
  lang: defaultLang(typeof navigator !== "undefined" ? navigator.language : "en"),
  checkSearchResults: false,
  localList: true,
  autoCheck: false,
  consentAt: null,
  idleSnapshots: true,
  investigatorMode: false,
};

export async function getSettings(): Promise<Settings> {
  const s = await chrome.storage.sync.get(DEFAULTS as unknown as Record<string, unknown>);
  return { ...DEFAULTS, ...(s as Partial<Settings>) };
}

export async function saveSettings(patch: Partial<Settings>): Promise<Settings> {
  await chrome.storage.sync.set(patch);
  return getSettings();
}

/** Automatic checking is active only with the user's recorded consent. */
export function autoCheckActive(s: Settings): boolean {
  return s.autoCheck && !!s.consentAt;
}

export function getDeviceId(): Promise<string> {
  return ensureDeviceId(
    async () => ((await chrome.storage.local.get("deviceId")).deviceId as string | undefined) ?? null,
    async (id) => chrome.storage.local.set({ deviceId: id }),
  );
}

export const EMPTY_LISTS: Lists = { version: "0", hosts: [], domains: [], recent_cert_domains: [], kit_files: [], syncedAt: null };

export async function getLists(): Promise<Lists> {
  const { lists } = await chrome.storage.local.get("lists");
  return { ...EMPTY_LISTS, ...((lists as Partial<Lists> | undefined) ?? {}) };
}

/** Back-compat shape used by the Search shields and options page. */
export interface LocalList {
  version: string | number;
  hosts: string[];
  syncedAt: string | null;
  error?: string | null;
}

export async function getLocalList(): Promise<LocalList> {
  const l = await getLists();
  return { version: l.version, hosts: [...l.hosts, ...l.domains], syncedAt: l.syncedAt, error: l.error };
}

/** scan_id -> {watchId, key, host}: watches created from this browser. */
export type WatchMap = Record<string, { watchId: string; key: string; host: string }>;

export async function getWatchMap(): Promise<WatchMap> {
  const { watches } = await chrome.storage.local.get("watches");
  return (watches as WatchMap | undefined) ?? {};
}

export async function setWatchMap(map: WatchMap): Promise<void> {
  await chrome.storage.local.set({ watches: map });
}
