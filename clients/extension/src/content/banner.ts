/** On every http(s) page:
 *  1. reviewer-confirmed high-risk site (on-device list) -> warning banner, no server call;
 *  2. otherwise the background classifies the page on the device (sensitive / well-known sites are skipped and
 *     nothing more happens);
 *  3. candidate pages are checked automatically (only after the user's consent): the toolbar badge shows the
 *     result; the full-page banner appears only for High risk. */
import { TIERS, t, type Lang, type ScanResult } from "@hami/shared";
import { send, type ClassifyData, type SnapshotResource } from "../lib/messages";
import { autoCheckActive, getSettings } from "../lib/settings";
import { WIDGET_CSS, dirFor } from "./overlay";

const HOST_ID = "hami-banner";
const SIGNALS = [
  /part[\s-]?time|work from (home|your phone)|daily tasks?|grab orders?/i,               // jobs / tasks
  /recharge|top[\s-]?up|deposit|withdraw/i,                                              // deposits
  /\bvip ?\d|invitation code|invite code|referral code/i,                                // levels / invites
  /guaranteed (profit|return)|daily (profit|return)|\d+(\.\d+)?\s?% (daily|per day)/i,   // investment
  /casino|slot games|jackpot|bet now|lucky ?spin|free spins/i,                           // gambling
  /card number|cvv|one[\s-]?time password|otp|verify your (card|account)/i,              // credentials
  /customs fee|redelivery fee|parcel (is )?on hold/i,                                    // parcel
  /وظائف|وظيفة|دوام جزئي|مهام يومية|اشحن الرصيد|إيداع|ايداع|سحب|رمز الدعوة|أرباح مضمونة|كازينو|رمز التحقق|رسوم الجمارك/,
];

function dismissed(): boolean {
  try {
    return sessionStorage.getItem("hami-banner-dismissed") === location.hostname;
  } catch {
    return false;
  }
}

function showBanner(lang: Lang, title: string, body: string, note: string, color: string, result?: ScanResult): void {
  if (dismissed() || document.getElementById(HOST_ID)) return;
  const host = document.createElement("div");
  host.id = HOST_ID;
  host.style.cssText = "all:initial;position:fixed;top:0;left:0;right:0;z-index:2147483647";
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `${WIDGET_CSS}
    .bar{display:flex;gap:12px;align-items:flex-start;padding:12px 16px;color:#fff;box-shadow:0 2px 10px rgba(0,0,0,.25)}
    .bar strong{display:block;font-size:15px}.bar p{margin:2px 0 0;font-size:13px}.bar .n{opacity:.85;font-size:12px}
    .bar button{margin-inline-start:auto;background:rgba(255,255,255,.2);color:#fff;border:1px solid rgba(255,255,255,.5);
      border-radius:8px;padding:4px 10px;cursor:pointer;font:inherit}
    .bar a{color:#fff;text-decoration:underline;cursor:pointer;font-size:12px}`;
  const bar = document.createElement("div");
  bar.className = "w bar";
  bar.dir = dirFor(lang);
  bar.style.background = color;
  const words = document.createElement("div");
  const s = document.createElement("strong");
  s.textContent = title;
  const p = document.createElement("p");
  p.textContent = body;
  const n = document.createElement("p");
  n.className = "n";
  n.textContent = note;
  words.append(s, p, n);
  if (result) {
    const a = document.createElement("a");
    a.textContent = t("openFullResult", lang);
    a.addEventListener("click", () => void send({ type: "openResult", scanId: result.scan_id, key: result.access_key }));
    words.append(a);
  }
  const close = document.createElement("button");
  close.textContent = t("dismiss", lang);
  close.addEventListener("click", () => {
    try {
      sessionStorage.setItem("hami-banner-dismissed", location.hostname);
    } catch {
      /* storage blocked */
    }
    host.remove();
  });
  bar.append(words, close);
  root.append(style, bar);
  document.documentElement.append(host);
}

function pageSignals(): number {
  const text = `${document.title}\n${(document.body?.innerText ?? "").slice(0, 8000)}`;
  return SIGNALS.filter((rx) => rx.test(text)).length;
}

/** File names of the page's own resources (stay on the device; compared with known kit file names). */
export function resourceNames(): string[] {
  const names = new Set<string>();
  for (const e of performance.getEntriesByType("resource") as PerformanceResourceTiming[]) {
    try {
      const n = new URL(e.name).pathname.split("/").pop();
      if (n && /\.(m?js|css)$/i.test(n)) names.add(n);
    } catch {
      /* ignore */
    }
  }
  return [...names].slice(0, 400);
}

const IDLE_MS = 10_000;

/** Resources the page loaded (PerformanceResourceTiming); query strings are stripped in the background. */
function pageResources(): SnapshotResource[] {
  const out: SnapshotResource[] = [];
  const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
  const statusOf = (e: PerformanceEntry): number | null => (e as unknown as { responseStatus?: number }).responseStatus || null;
  if (nav) out.push({ url: location.href, type: "main_frame", status: statusOf(nav), duration_ms: Math.round(nav.duration),
                      size: nav.transferSize || null });
  for (const e of performance.getEntriesByType("resource") as PerformanceResourceTiming[]) {
    out.push({ url: e.name, type: e.initiatorType || "other", status: statusOf(e), duration_ms: Math.round(e.duration),
               size: e.transferSize || e.encodedBodySize || null });
  }
  return out.slice(0, 600);
}

/** After 10 s without mouse, keyboard, scroll or touch activity, send one snapshot for this page load.
 * (Measured here: chrome.idle's minimum is 15 s.) */
function watchIdle(lang: Lang): void {
  let timer = 0;
  let sent = false;
  const events = ["mousemove", "mousedown", "keydown", "scroll", "wheel", "touchstart"];
  const reset = (): void => {
    clearTimeout(timer);
    timer = window.setTimeout(fire, IDLE_MS);
  };
  const fire = (): void => {
    if (sent) return;
    if (document.visibilityState !== "visible") {
      reset();
      return;
    }
    sent = true;
    events.forEach((ev) => window.removeEventListener(ev, reset, true));
    const text = (document.body?.innerText ?? "").slice(0, 20000);
    void send({ type: "snapshot", payload: { page_url: location.href, resources: pageResources(), visible_text: text, lang } })
      .then((r) => document.dispatchEvent(new CustomEvent("hami-snapshot", { detail: { ok: r.ok } })));
  };
  events.forEach((ev) => window.addEventListener(ev, reset, { capture: true, passive: true }));
  reset();
}

/** Investigator mode: save the recording after 10 s without activity. */
async function investigatorIdleSave(): Promise<void> {
  const st = await send<{ recording: boolean }>({ type: "investigatorStatus" });
  if (!st.ok || !st.data.recording) return;
  let timer = 0;
  const events = ["mousemove", "mousedown", "keydown", "scroll", "wheel", "touchstart"];
  const fire = (): void => {
    events.forEach((ev) => window.removeEventListener(ev, reset, true));
    void send({ type: "investigatorSave" }).then((r) =>
      document.dispatchEvent(new CustomEvent("hami-evidence", { detail: r.ok ? r.data : { error: r.error } })));
  };
  const reset = (): void => {
    clearTimeout(timer);
    timer = window.setTimeout(fire, IDLE_MS);
  };
  events.forEach((ev) => window.addEventListener(ev, reset, { capture: true, passive: true }));
  reset();
}

async function main(): Promise<void> {
  void investigatorIdleSave();
  const s = await getSettings();
  const lang = s.lang;
  const cls = await send<ClassifyData>({ type: "classify", url: location.href, resourceNames: resourceNames() });
  if (!cls.ok) return;
  if (cls.data.highRisk) {
    if (s.localList) showBanner(lang, t("bannerTitle", lang), t("bannerBody", lang), t("bannerLocal", lang), TIERS.high_risk.color);
    return;
  }
  if (cls.data.skip || !autoCheckActive(s)) return; // sensitive / well-known / no consent: nothing is sent
  const reasons = [...cls.data.reasons];
  if (pageSignals() >= 1) reasons.push("page_signals");
  const res = await send<ScanResult>({ type: "autoCheck", url: location.href, reasons });
  if (res.ok && res.data.tier === "high_risk") {
    const style = TIERS.high_risk;
    showBanner(lang, `${t("autoCheckTitle", lang)}: ${style.label[lang]}`, res.data.headline?.[lang] ?? style.headline[lang],
      res.data.clues[0]?.text[lang] ?? "", style.color, res.data);
  }
  document.dispatchEvent(new CustomEvent("hami-candidate", { detail: { checked: res.ok } }));
  if (s.idleSnapshots) watchIdle(lang);
}

void main();
