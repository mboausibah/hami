import { DEFAULT_API_BASE, defaultLang, ensureDeviceId, type Lang } from "@hami/shared";

export interface Settings {
  serverUrl: string;
  lang: Lang;
  /** Send result hostnames (only) to POST /lookup/hosts on Google Search. Off by default. */
  checkSearchResults: boolean;
  /** Use the on-device reviewer-confirmed high-risk list (no server call). On by default. */
  localList: boolean;
  /** Auto-check job/task-looking pages (sends their address). Off by default. */
  autoCheck: boolean;
}

export const DEFAULTS: Settings = {
  serverUrl: DEFAULT_API_BASE,
  lang: defaultLang(typeof navigator !== "undefined" ? navigator.language : "en"),
  checkSearchResults: false,
  localList: true,
  autoCheck: false,
};

export async function getSettings(): Promise<Settings> {
  const s = await chrome.storage.sync.get(DEFAULTS as unknown as Record<string, unknown>);
  return { ...DEFAULTS, ...(s as Partial<Settings>) };
}

export async function saveSettings(patch: Partial<Settings>): Promise<Settings> {
  await chrome.storage.sync.set(patch);
  return getSettings();
}

export function getDeviceId(): Promise<string> {
  return ensureDeviceId(
    async () => ((await chrome.storage.local.get("deviceId")).deviceId as string | undefined) ?? null,
    async (id) => chrome.storage.local.set({ deviceId: id }),
  );
}

export interface LocalList {
  version: number;
  hosts: string[];
  syncedAt: string | null;
  error?: string | null;
}

export async function getLocalList(): Promise<LocalList> {
  const { highRisk } = await chrome.storage.local.get("highRisk");
  return (highRisk as LocalList | undefined) ?? { version: 0, hosts: [], syncedAt: null };
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
