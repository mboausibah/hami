/** Google Maps business check: reads the open business panel's name and website link and offers
 * "Check this business website", which scans the website with source_type=maps and the listing
 * name, so a listing-identity mismatch is flagged. */
import { hostOf, t, type Lang } from "@hami/shared";
import { MAPS, first } from "../selectors";
import { getSettings } from "../lib/settings";
import { WIDGET_CSS, checkInto, dirFor } from "./overlay";

const HOST_ID = "hami-maps-check";
let lang: Lang = "en";
let current = "";

function websiteUrl(a: HTMLAnchorElement): string | null {
  try {
    const u = new URL(a.href);
    if (/(^|\.)google\.[a-z.]+$/.test(u.hostname) && u.pathname === "/url") return u.searchParams.get("q");
    return u.protocol.startsWith("http") ? u.href : null;
  } catch {
    return null;
  }
}

function render(name: string, url: string): void {
  document.getElementById(HOST_ID)?.remove();
  const host = document.createElement("div");
  host.id = HOST_ID;
  host.style.cssText = "all:initial;position:fixed;z-index:2147483645;bottom:24px;inset-inline-start:24px";
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `${WIDGET_CSS}
    .panel{width:340px;background:#fff;border:1px solid #d9dee5;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.18);padding:12px}
    .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
    .x{background:none;border:0;cursor:pointer;font-size:16px;color:#5b6876}
    .name{font-weight:700}.site{direction:ltr;unicode-bidi:isolate;font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#5b6876}`;
  const panel = document.createElement("div");
  panel.className = "w panel";
  panel.dir = dirFor(lang);
  const top = document.createElement("div");
  top.className = "top";
  const title = document.createElement("strong");
  title.textContent = "حامي Hami";
  const close = document.createElement("button");
  close.className = "x";
  close.textContent = "×";
  close.title = t("dismiss", lang);
  close.addEventListener("click", () => host.remove());
  top.append(title, close);
  const nameEl = document.createElement("div");
  nameEl.innerHTML = "";
  nameEl.append(`${t("listing", lang)}: `);
  const n = document.createElement("span");
  n.className = "name";
  n.textContent = name;
  nameEl.append(n);
  const siteEl = document.createElement("div");
  siteEl.className = "site";
  siteEl.textContent = hostOf(url) ?? url;
  const btn = document.createElement("button");
  btn.className = "btn";
  btn.textContent = t("checkBusinessWebsite", lang);
  btn.style.marginTop = "8px";
  const out = document.createElement("div");
  out.style.marginTop = "8px";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    await checkInto(out, url, lang, "maps", name);
    btn.disabled = false;
  });
  panel.append(top, nameEl, siteEl, btn, out);
  root.append(style, panel);
  document.documentElement.append(host);
}

function scan(): void {
  const nameEl = first<HTMLElement>(MAPS.businessName);
  const siteEl = first<HTMLAnchorElement>(MAPS.website);
  const name = nameEl?.textContent?.trim() ?? "";
  const url = siteEl ? websiteUrl(siteEl) : null;
  if (!name || !url) {
    if (current) {
      document.getElementById(HOST_ID)?.remove();
      current = "";
    }
    return;
  }
  const key = `${name}|${url}`;
  if (key === current) return;
  current = key;
  render(name, url);
}

async function main(): Promise<void> {
  lang = (await getSettings()).lang;
  scan();
  let timer: number | undefined;
  new MutationObserver(() => {
    clearTimeout(timer);
    timer = window.setTimeout(scan, 600);
  }).observe(document.body, { childList: true, subtree: true });
}

void main();
