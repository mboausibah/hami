import { hostOf, isCheckableUrl, t, type HamiAlert, type Lang, type PageSignals, type ScanResult } from "@hami/shared";
import { MAPS } from "../selectors";
import { send, type AlertsData } from "../lib/messages";
import { getSettings } from "../lib/settings";
import { applyLang, errorText, injectCardCss, showResult } from "../lib/ui";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
let lang: Lang = "en";
let targetUrl: string | null = null;
let lastResult: ScanResult | null = null;

async function init(): Promise<void> {
  injectCardCss();
  lang = (await getSettings()).lang;
  applyLang(lang);
  $("open-options").title = t("openOptions", lang);
  $("open-options").addEventListener("click", () => chrome.runtime.openOptionsPage());
  $("tab-check").addEventListener("click", () => switchTab("check"));
  $("tab-updates").addEventListener("click", () => switchTab("updates"));
  $("check-btn").addEventListener("click", () => runCheck(false));
  $("recheck").addEventListener("click", () => runCheck(true));
  $("open-full").addEventListener("click", () => {
    if (lastResult) void send({ type: "openResult", scanId: lastResult.scan_id, key: lastResult.access_key });
  });

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  targetUrl = isCheckableUrl(tab?.url) ? tab!.url! : null;
  // When the popup page is opened as a tab (automated checks, screenshots), ?target= supplies the page.
  const forced = new URLSearchParams(location.search).get("target");
  if (forced && isCheckableUrl(forced)) targetUrl = forced;
  if (tab?.id !== undefined && tab.url && /^https:\/\/www\.google\.com\/maps/.test(tab.url)) await prefillFromMaps(tab.id);
  $("target-host").textContent = targetUrl ? hostOf(targetUrl) ?? "" : t("cannotCheckPage", lang);
  ($("check-btn") as HTMLButtonElement).disabled = !targetUrl;

  if (targetUrl) {
    const key = `result:${targetUrl}`;
    const cached = (await chrome.storage.session.get(key))[key] as { at: number; result: ScanResult } | undefined;
    if (cached && Date.now() - cached.at < 30 * 60_000) await render(cached.result);
  }
  void loadUpdates(false);
  if (tab?.id !== undefined) void setupInvestigator(tab.id, tab.url ?? "");
}

async function setupInvestigator(tabId: number, url: string): Promise<void> {
  const st = await send<{ recording: boolean; enabled: boolean }>({ type: "investigatorStatus", tabId });
  if (!st.ok || !st.data.enabled || !isCheckableUrl(url)) return;
  $("investigator").hidden = false;
  const startBtn = $("inv-start");
  const saveBtn = $("inv-save");
  const status = $("inv-status");
  const show = (recording: boolean): void => {
    startBtn.hidden = recording;
    saveBtn.hidden = !recording;
    status.textContent = recording ? t("investigatorRecording", lang) : "";
  };
  show(st.data.recording);
  startBtn.addEventListener("click", async () => {
    const r = await send({ type: "investigatorStart", tabId, url });
    if (r.ok) show(true);
    else status.textContent = r.error;
  });
  saveBtn.addEventListener("click", async () => {
    const r = await send<{ filename: string; sha256: string; entries: number; uploaded?: { evidence_id: number } }>(
      { type: "investigatorSave", tabId });
    show(false);
    status.textContent = r.ok ? `${t("investigatorSaved", lang)} ${r.data.filename} · SHA-256 ${r.data.sha256.slice(0, 16)}…` +
      (r.data.uploaded ? ` · ${t("investigatorUploaded", lang)} #${r.data.uploaded.evidence_id}` : "") : r.error;
  });
}

/** On a Google Maps business panel, check the business website with the listing name (activeTab + scripting). */
async function prefillFromMaps(tabId: number): Promise<void> {
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId },
      args: [MAPS.businessName, MAPS.website],
      func: (nameSel: string[], siteSel: string[]) => {
        const q = (sels: string[]) => sels.map((s) => document.querySelector(s)).find(Boolean) as HTMLElement | undefined;
        const name = q(nameSel)?.textContent?.trim() ?? null;
        const site = (q(siteSel) as HTMLAnchorElement | undefined)?.href ?? null;
        return { name, site };
      },
    });
    const v = res?.result as { name: string | null; site: string | null } | undefined;
    if (v?.site) {
      targetUrl = v.site;
      if (v.name) {
        ($("listing-name") as HTMLInputElement).value = v.name;
        ($("listing-box") as HTMLDetailsElement).open = true;
      }
    }
  } catch {
    /* panel not open or selectors changed: plain page check still works */
  }
}

function switchTab(which: "check" | "updates"): void {
  $("view-check").hidden = which !== "check";
  $("view-updates").hidden = which !== "updates";
  $("tab-check").classList.toggle("on", which === "check");
  $("tab-updates").classList.toggle("on", which === "updates");
  if (which === "updates") void loadUpdates(true);
}

async function runCheck(force: boolean): Promise<void> {
  if (!targetUrl) return;
  const btn = $("check-btn") as HTMLButtonElement;
  const status = $("status");
  btn.disabled = true;
  status.hidden = false;
  status.className = "status";
  status.textContent = t("checking", lang);
  const listing = ($("listing-name") as HTMLInputElement).value.trim();
  const res = await send<ScanResult>({
    type: "scan",
    url: targetUrl,
    sourceType: listing ? (/google\.com\/maps/.test(targetUrl) ? "maps" : "search") : "extension",
    listingName: listing || null,
    force,
    pageSignals: await tabSignals(targetUrl),
  });
  btn.disabled = false;
  if (!res.ok) {
    status.className = "status err";
    status.textContent = errorText(res, lang);
    return;
  }
  status.hidden = true;
  await render(res.data);
}

/** Ask the open tab for its page structure (computed on the device by the content script). */
async function tabSignals(url: string): Promise<PageSignals | null> {
  try {
    const tabs = await chrome.tabs.query({});
    const bare = (u?: string): string => (u ?? "").split("#")[0];
    // Same page as the automatic check: the active tab first, then any tab showing this URL (fragment ignored).
    const tab = tabs.find((x) => x.active && bare(x.url) === bare(url)) ?? tabs.find((x) => bare(x.url) === bare(url));
    if (tab?.id === undefined) return null;
    return await Promise.race([
      chrome.tabs.sendMessage(tab.id, { type: "collectPageSignals" }) as Promise<PageSignals | null>,
      new Promise<null>((r) => setTimeout(() => r(null), 2000)),
    ]);
  } catch {
    return null;
  }
}

async function render(r: ScanResult): Promise<void> {
  lastResult = r;
  await showResult($("result"), r, lang);
  $("result-actions").hidden = false;
}

function fmt(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(lang === "ar" ? "ar-AE" : "en-AE", { dateStyle: "medium", timeStyle: "short" }) : "";
}

async function loadUpdates(markSeen: boolean): Promise<void> {
  const res = await send<AlertsData>({ type: "alerts" });
  const box = $("alerts");
  const count = $("updates-count");
  if (!res.ok) {
    box.replaceChildren(Object.assign(document.createElement("p"), { className: "empty", textContent: errorText(res, lang) }));
    return;
  }
  const { alerts, unseen, watches } = res.data;
  count.hidden = unseen.length === 0;
  count.textContent = String(unseen.length);
  box.replaceChildren();
  if (!alerts.length) box.append(Object.assign(document.createElement("p"), { className: "empty", textContent: t("noUpdates", lang) }));
  for (const a of alerts) box.append(alertRow(a, unseen.includes(a.alert_id)));
  const wbox = $("watches");
  wbox.replaceChildren();
  for (const w of watches) {
    const row = document.createElement("div");
    row.className = "watch-row";
    const h = document.createElement("bdi");
    h.dir = "ltr";
    h.textContent = w.host;
    const stop = document.createElement("button");
    stop.className = "link";
    stop.textContent = t("stopWatching", lang);
    stop.addEventListener("click", async () => {
      await send({ type: "unwatch", scanId: w.scan_id });
      row.remove();
    });
    row.append(h, stop);
    wbox.append(row);
  }
  if (markSeen && unseen.length) {
    await send({ type: "markAlertsSeen" });
    count.hidden = true;
  }
}

function alertRow(a: HamiAlert, isNew: boolean): HTMLElement {
  const d = document.createElement("div");
  d.className = `alert${isNew ? " new" : ""}${a.withdrawn ? " withdrawn" : ""}`;
  const tag = document.createElement("span");
  tag.className = a.withdrawn ? "tag w" : "tag";
  tag.textContent = a.withdrawn ? t("withdrawn", lang) : isNew ? t("newBadge", lang) : t("relatedSite", lang);
  const host = document.createElement("bdi");
  host.dir = "ltr";
  host.textContent = a.related_host_defanged ?? "";
  const head = document.createElement("div");
  head.append(tag, host);
  const reason = document.createElement("div");
  reason.textContent = a.reason[lang];
  const when = document.createElement("div");
  when.className = "when";
  when.textContent = `${a.watched_host} · ${fmt(a.sent_at)}${a.withdrawn && a.withdrawn_reason ? ` · ${a.withdrawn_reason}` : ""}`;
  d.append(head, reason, when);
  return d;
}

void init();
