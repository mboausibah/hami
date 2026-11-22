/** On every page: warning banner when the site is on the on-device, reviewer-confirmed high-risk list
 * (no server call). Optional auto-check (off by default) for job/task-scam keyword pages. */
import { TIERS, hostMatches, t, type Lang, type ScanResult } from "@hami/shared";
import { send } from "../lib/messages";
import { getLocalList, getSettings } from "../lib/settings";
import { WIDGET_CSS, dirFor } from "./overlay";

const HOST_ID = "hami-banner";
const JOB_HINTS = [
  /part[\s-]?time/i, /daily tasks?/i, /work from (home|your phone)/i, /commission/i, /recharge|top[\s-]?up/i,
  /\bvip ?\d/i, /invitation code|invite code/i, /earn .{0,20} per (day|task|order)/i, /grab orders?/i,
  /وظائف|وظيفة/, /دوام جزئي/, /مهام يومية/, /عمولة/, /اشحن|شحن الرصيد/, /رمز الدعوة/, /العمل من المنزل/,
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

function looksJobLike(): boolean {
  const text = `${document.title}\n${(document.body?.innerText ?? "").slice(0, 6000)}`;
  return JOB_HINTS.filter((rx) => rx.test(text)).length >= 2;
}

async function main(): Promise<void> {
  const [s, list] = await Promise.all([getSettings(), getLocalList()]);
  const lang = s.lang;
  if (s.localList && list.hosts.some((h) => hostMatches(location.hostname, h))) {
    showBanner(lang, t("bannerTitle", lang), t("bannerBody", lang), t("bannerLocal", lang), TIERS.high_risk.color);
    return;
  }
  if (s.autoCheck && looksJobLike()) {
    const res = await send<ScanResult>({ type: "autoCheck", url: location.href });
    if (res.ok && (res.data.tier === "high_risk" || res.data.tier === "caution")) {
      const style = TIERS[res.data.tier];
      showBanner(lang, `${t("autoCheckTitle", lang)}: ${style.label[lang]}`, res.data.headline?.[lang] ?? style.headline[lang],
        res.data.clues[0]?.text[lang] ?? "", style.color, res.data);
    }
  }
}

void main();
