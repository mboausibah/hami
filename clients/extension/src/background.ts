/** Background service worker: context menu, API calls on behalf of pages/content scripts, 30-minute
 * sync of the reviewer-approved high-risk list, unread-alerts badge. */
import { HamiApi, HamiApiError, SYNC_INTERVAL_MIN, hostOf, t, type HamiAlert, type ScanResult } from "@hami/shared";
import type { AlertsData, Request, Response } from "./lib/messages";
import { getDeviceId, getLocalList, getSettings, getWatchMap, setWatchMap, type LocalList } from "./lib/settings";

const MENU_ID = "hami-check-link";
const ALARM = "hami-sync";

async function api(): Promise<HamiApi> {
  const [s, device] = await Promise.all([getSettings(), getDeviceId()]);
  return new HamiApi(s.serverUrl, device);
}

async function setupMenu(): Promise<void> {
  const s = await getSettings();
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({ id: MENU_ID, title: t("checkThisLink", s.lang), contexts: ["link"] });
}

async function syncHighRisk(): Promise<LocalList> {
  try {
    const list = await (await api()).highRiskHosts();
    const value: LocalList = { version: list.version, hosts: list.hosts, syncedAt: new Date().toISOString(), error: null };
    await chrome.storage.local.set({ highRisk: value });
    return value;
  } catch (e) {
    const prev = await getLocalList();
    const value = { ...prev, error: (e as Error).message };
    await chrome.storage.local.set({ highRisk: value });
    return value;
  }
}

async function seenAlertKeys(): Promise<string[]> {
  return ((await chrome.storage.local.get("seenAlerts")).seenAlerts as string[] | undefined) ?? [];
}

/** An alert counts as unread when it is new, or when it was withdrawn after the user saw it. */
function alertKey(a: HamiAlert): string {
  return `${a.alert_id}:${a.withdrawn ? "w" : "a"}`;
}

async function refreshAlerts(): Promise<AlertsData> {
  const client = await api();
  const [{ alerts }, { watches }] = await Promise.all([client.alerts(), client.watches()]);
  const seen = new Set(await seenAlertKeys());
  const unseen = alerts.filter((a) => !seen.has(alertKey(a))).map((a) => a.alert_id);
  await chrome.storage.local.set({ alertsCache: alerts });
  await chrome.action.setBadgeBackgroundColor({ color: "#b42318" });
  await chrome.action.setBadgeText({ text: unseen.length ? String(unseen.length) : "" });
  return { alerts, unseen, watches };
}

async function syncAll(): Promise<void> {
  await syncHighRisk();
  try {
    await refreshAlerts();
  } catch {
    /* server unreachable: keep the last badge */
  }
}

function fail(e: unknown): Response<never> {
  if (e instanceof HamiApiError) return { ok: false, error: e.message, status: e.status };
  return { ok: false, error: (e as Error).message ?? String(e) };
}

async function rememberResult(r: ScanResult, url: string): Promise<void> {
  const key = `result:${url}`;
  await chrome.storage.session.set({ [key]: { at: Date.now(), result: r } });
}

const autoChecked = new Set<string>();

async function handle(req: Request): Promise<Response<unknown>> {
  const s = await getSettings();
  switch (req.type) {
    case "scan": {
      const r = await (await api()).scan(req.url, {
        sourceType: req.sourceType ?? "extension",
        listingName: req.listingName,
        lang: s.lang,
        force: req.force,
      });
      await rememberResult(r, req.url);
      return { ok: true, data: r };
    }
    case "autoCheck": {
      // Only when the user enabled auto-check; once per site per browser session.
      if (!s.autoCheck) return { ok: false, error: "auto-check disabled" };
      const host = hostOf(req.url);
      if (!host || autoChecked.has(host)) return { ok: false, error: "already checked" };
      autoChecked.add(host);
      const r = await (await api()).scan(req.url, { sourceType: "extension", lang: s.lang });
      await rememberResult(r, req.url);
      return { ok: true, data: r };
    }
    case "getScan":
      return { ok: true, data: await (await api()).getScan(req.scanId, req.key) };
    case "lookup": {
      // Hostnames only, and only if the user turned on "Check search results".
      if (!s.checkSearchResults) return { ok: true, data: {} };
      const hosts = [...new Set(req.hosts.map((h) => h.toLowerCase()))].slice(0, 60);
      const { results } = await (await api()).lookupHosts(hosts);
      return { ok: true, data: results };
    }
    case "watch": {
      const w = await (await api()).watch(req.scanId, req.key);
      const map = await getWatchMap();
      map[String(req.scanId)] = { watchId: w.watch_id, key: req.key, host: req.host };
      await setWatchMap(map);
      return { ok: true, data: w };
    }
    case "unwatch": {
      const map = await getWatchMap();
      const entry = map[String(req.scanId)];
      if (entry) await (await api()).unwatch(entry.watchId).catch(() => undefined);
      delete map[String(req.scanId)];
      await setWatchMap(map);
      return { ok: true, data: true };
    }
    case "alerts":
      return { ok: true, data: await refreshAlerts() };
    case "markAlertsSeen": {
      const cached = ((await chrome.storage.local.get("alertsCache")).alertsCache as HamiAlert[] | undefined) ?? [];
      const seen = new Set(await seenAlertKeys());
      cached.forEach((a) => seen.add(alertKey(a)));
      await chrome.storage.local.set({ seenAlerts: [...seen].slice(-500) });
      await chrome.action.setBadgeText({ text: "" });
      return { ok: true, data: true };
    }
    case "syncNow":
      await setupMenu();
      return { ok: true, data: await syncHighRisk() };
    case "openResult":
      await chrome.tabs.create({ url: chrome.runtime.getURL(`result/result.html?scan=${req.scanId}&k=${encodeURIComponent(req.key)}`) });
      return { ok: true, data: true };
  }
}

chrome.runtime.onMessage.addListener((req: Request, _sender, sendResponse) => {
  handle(req).then(sendResponse, (e) => sendResponse(fail(e)));
  return true; // async response
});

chrome.runtime.onInstalled.addListener(async () => {
  await getDeviceId();
  await setupMenu();
  await chrome.alarms.create(ALARM, { periodInMinutes: SYNC_INTERVAL_MIN, delayInMinutes: 0.1 });
  await syncAll();
});

chrome.runtime.onStartup.addListener(async () => {
  await setupMenu();
  await syncAll();
});

chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === ALARM) void syncAll();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync" && (changes.lang || changes.serverUrl)) {
    void setupMenu();
    if (changes.serverUrl) void syncAll();
  }
});

chrome.contextMenus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== MENU_ID || !info.linkUrl) return;
  await chrome.tabs.create({
    url: chrome.runtime.getURL(`result/result.html?url=${encodeURIComponent(info.linkUrl)}&source=extension`),
  });
});
