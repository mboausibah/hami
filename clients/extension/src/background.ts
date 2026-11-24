/** Background service worker: context menu, API calls on behalf of pages/content scripts, 30-minute sync of
 * the on-device lists (reviewer-confirmed hosts/domains, recently certificate-logged domains, kit file names),
 * on-device pre-filter + automatic checking (after consent), per-tab result badge, unread-alerts badge. */
import { HamiApi, HamiApiError, SYNC_INTERVAL_MIN, TIER_RANK, hostOf, redactText, stripUrl, t, type HamiAlert, type ScanResult,
         type Tier } from "@hami/shared";
import type { AlertsData, Request, Response, SnapshotResource } from "./lib/messages";
import * as investigator from "./lib/investigator";
import { classify, type Lists } from "./lib/prefilter";
import { autoCheckActive, getDeviceId, getLists, getSettings, getWatchMap, saveSettings, setWatchMap } from "./lib/settings";

const MENU_ID = "hami-check-link";
const ALARM = "hami-sync";
const AUTO_PER_HOUR = 30;              // device-side cap on automatic checks
const AUTO_HOST_TTL_MS = 6 * 3600_000; // re-check a site automatically at most every 6 hours
const BADGE: Record<Tier, { text: string; color: string } | null> = {
  high_risk: { text: "!", color: "#b42318" },
  caution: { text: "?", color: "#d29a00" },
  no_strong_signals: { text: "✓", color: "#1a7f37" },
  insufficient_evidence: null,
};

// ---- idle-snapshot support: what each tab loaded, in memory only, recorded only while automatic checking is on.
const MAX_TAB_RESOURCES = 600;
const tabRequests = new Map<number, Map<string, SnapshotResource>>();
let recording = false;
void getSettings().then((s) => { recording = autoCheckActive(s) && s.idleSnapshots; });

function recordRequest(d: { tabId: number; url: string; type: string }, status: number | null): void {
  if (!recording || d.tabId < 0) return;
  const url = stripUrl(d.url);
  if (!url) return;
  const m = tabRequests.get(d.tabId) ?? new Map<string, SnapshotResource>();
  if (m.size >= MAX_TAB_RESOURCES && !m.has(url)) return;
  m.set(url, { url, type: d.type, status, duration_ms: null, size: null });
  tabRequests.set(d.tabId, m);
}
chrome.webRequest.onCompleted.addListener((d) => recordRequest(d, d.statusCode), { urls: ["<all_urls>"] });
chrome.webRequest.onErrorOccurred.addListener((d) => recordRequest(d, null), { urls: ["<all_urls>"] });

async function api(): Promise<HamiApi> {
  const [s, device] = await Promise.all([getSettings(), getDeviceId()]);
  return new HamiApi(s.serverUrl, device);
}

async function setupMenu(): Promise<void> {
  const s = await getSettings();
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({ id: MENU_ID, title: t("checkThisLink", s.lang), contexts: ["link"] });
}

async function syncLists(): Promise<Lists> {
  try {
    const s = await getSettings();
    const res = await fetch(`${s.serverUrl.replace(/\/+$/, "")}/indicators/local-lists`, { headers: { "X-Device-Id": await getDeviceId() } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as Omit<Lists, "syncedAt">;
    const value: Lists = { ...data, syncedAt: new Date().toISOString(), error: null };
    await chrome.storage.local.set({ lists: value });
    return value;
  } catch (e) {
    const prev = await getLists();
    const value = { ...prev, error: (e as Error).message };
    await chrome.storage.local.set({ lists: value });
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
  await syncLists();
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
  await chrome.storage.session.set({ [`result:${url}`]: { at: Date.now(), result: r } });
}

/** Coloured badge on the toolbar icon for this tab (green / amber / red). */
async function showTabBadge(tabId: number | undefined, tier: Tier | null): Promise<void> {
  if (tabId === undefined) return;
  const b = tier ? BADGE[tier] : null;
  await chrome.action.setBadgeText({ tabId, text: b ? b.text : "" });
  if (b) await chrome.action.setBadgeBackgroundColor({ tabId, color: b.color });
}

async function autoAllowed(host: string): Promise<boolean> {
  const { autoLog } = await chrome.storage.session.get("autoLog");
  const log = ((autoLog as number[] | undefined) ?? []).filter((ts) => Date.now() - ts < 3600_000);
  const { [`auto:${host}`]: last } = await chrome.storage.session.get(`auto:${host}`);
  if (log.length >= AUTO_PER_HOUR || (typeof last === "number" && Date.now() - last < AUTO_HOST_TTL_MS)) return false;
  log.push(Date.now());
  await chrome.storage.session.set({ autoLog: log, [`auto:${host}`]: Date.now() });
  return true;
}

async function handle(req: Request, sender: chrome.runtime.MessageSender): Promise<Response<unknown>> {
  const s = await getSettings();
  const tabId = sender.tab?.id;
  switch (req.type) {
    case "scan": {
      const r = await (await api()).scan(req.url, {
        sourceType: req.sourceType ?? "extension",
        listingName: req.listingName,
        lang: s.lang,
        force: req.force,
        // Page structure only for the page itself, and never for sites the on-device pre-filter skips.
        pageSignals: req.pageSignals && !classify(req.url, await getLists()).skip ? req.pageSignals : null,
      });
      await rememberResult(r, req.url);
      return { ok: true, data: r };
    }
    case "classify": {
      // On-device decision; no network.
      return { ok: true, data: classify(req.url, await getLists(), req.resourceNames ?? []) };
    }
    case "autoCheck": {
      if (!autoCheckActive(s)) return { ok: false, error: "automatic checking is off (no consent)" };
      const cls = classify(req.url, await getLists());
      if (cls.skip) return { ok: false, error: `skipped: ${cls.reason}` };
      const host = hostOf(req.url);
      if (!host) return { ok: false, error: "not checkable" };
      const key = `result:${req.url}`;
      const cached = (await chrome.storage.session.get(key))[key] as { at: number; result: ScanResult } | undefined;
      // A result whose evidence was still pending (certificate age) is only reused for a minute, so the automatic
      // check and "Check this page" converge on the same tier.
      const ttl = cached?.result.pending?.length ? 60_000 : AUTO_HOST_TTL_MS;
      if (cached && Date.now() - cached.at < ttl) {
        await showTabBadge(tabId, cached.result.tier);
        return { ok: true, data: cached.result };
      }
      if (!(await autoAllowed(host))) return { ok: false, error: "rate limited on this device" };
      const r = await (await api()).scan(req.url, { sourceType: "extension", lang: s.lang, pageSignals: req.pageSignals ?? null });
      await rememberResult(r, req.url);
      await chrome.storage.session.set({ [`tab:${tabId}`]: { scanId: r.scan_id, key: r.access_key, url: req.url, reasons: req.reasons } });
      await showTabBadge(tabId, r.tier);
      return { ok: true, data: r };
    }
    case "snapshot": {
      // One idle snapshot per page load, candidates only, with consent. Sanitized again here before sending.
      if (!autoCheckActive(s) || !s.idleSnapshots) return { ok: false, error: "snapshots are off" };
      const page = stripUrl(req.payload.page_url);
      if (!page || classify(page, await getLists()).skip) return { ok: false, error: "not a candidate" };
      const onceKey = `snap:${tabId}:${page}`;
      if ((await chrome.storage.session.get(onceKey))[onceKey]) return { ok: false, error: "already sent for this page load" };
      await chrome.storage.session.set({ [onceKey]: Date.now() });
      const merged = new Map<string, SnapshotResource>();
      for (const r of req.payload.resources) {
        const u = stripUrl(r.url);
        if (u) merged.set(u, { ...r, url: u });
      }
      for (const [u, r] of tabRequests.get(tabId ?? -1) ?? []) {
        const prev = merged.get(u);
        merged.set(u, prev ? { ...prev, status: r.status ?? prev.status, type: prev.type || r.type } : r);
      }
      const tab = (await chrome.storage.session.get(`tab:${tabId}`))[`tab:${tabId}`] as
        { scanId: number; key: string; url: string } | undefined;
      const link = tab && stripUrl(tab.url) === page ? { scan_id: tab.scanId, k: tab.key } : {};
      const r = await (await api()).snapshot({
        page_url: page, resources: [...merged.values()].slice(0, MAX_TAB_RESOURCES),
        visible_text: redactText(req.payload.visible_text).slice(0, 20000), lang: req.payload.lang, ...link,
      });
      const prevKey = `result:${tab?.url ?? page}`;
      const prev = (await chrome.storage.session.get(prevKey))[prevKey] as { result: ScanResult } | undefined;
      if (r.tier && (!prev?.result.tier || TIER_RANK[r.tier] < TIER_RANK[prev.result.tier])) {
        await showTabBadge(tabId, r.tier);
        await rememberResult(r, tab?.url ?? page);
      }
      return { ok: true, data: r };
    }
    case "investigatorStart": {
      if (!s.investigatorMode) return { ok: false, error: "investigator mode is off (Options)" };
      const id = req.tabId ?? tabId;
      const url = req.url ?? sender.tab?.url;
      if (id === undefined || !url) return { ok: false, error: "no tab" };
      const cls = classify(url, await getLists());
      // Never on sites skipped by the pre-filter (sensitive / well-known); confirmed high-risk sites are allowed.
      if (cls.skip && !cls.highRisk) return { ok: false, error: `not allowed on this site (${cls.reason})` };
      await investigator.start(id, url);
      return { ok: true, data: { recording: true } };
    }
    case "investigatorStatus":
      return { ok: true, data: { recording: investigator.isRecording(req.tabId ?? tabId ?? -1), enabled: s.investigatorMode } };
    case "investigatorSave": {
      const id = req.tabId ?? tabId;
      if (id === undefined || !investigator.isRecording(id)) return { ok: false, error: "this tab is not being recorded" };
      const saved = await investigator.save(id);
      const result: Record<string, unknown> = { filename: saved.filename, sha256: saved.sha256, entries: saved.entries };
      if (req.upload ?? s.evidenceUpload) {
        const up = await (await api()).uploadEvidence({ page_url: saved.pageUrl, har_text: saved.harText,
                                                        client_sha256: saved.sha256, entries: saved.entries });
        result.uploaded = { evidence_id: up.evidence_id, scan_id: up.scan_id, tier: up.tier, hash_match: up.hash_match };
      }
      return { ok: true, data: result };
    }
    case "consent": {
      const next = await saveSettings(req.agree ? { autoCheck: true, consentAt: new Date().toISOString() }
                                                : { autoCheck: false, consentAt: null });
      return { ok: true, data: next };
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
      return { ok: true, data: await syncLists() };
    case "openResult":
      await chrome.tabs.create({ url: chrome.runtime.getURL(`result/result.html?scan=${req.scanId}&k=${encodeURIComponent(req.key)}`) });
      return { ok: true, data: true };
  }
}

chrome.runtime.onMessage.addListener((req: Request, sender, sendResponse) => {
  handle(req, sender).then(sendResponse, (e) => sendResponse(fail(e)));
  return true; // async response
});

chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    // One-time consent screen first: automatic checking stays off until the user agrees.
    await chrome.tabs.create({ url: chrome.runtime.getURL("consent/consent.html") });
  }
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

chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.status === "loading") {
    void showTabBadge(tabId, null);
    tabRequests.delete(tabId);
  }
});
chrome.tabs.onRemoved.addListener((tabId) => tabRequests.delete(tabId));

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync") void getSettings().then((s) => { recording = autoCheckActive(s) && s.idleSnapshots; });
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
