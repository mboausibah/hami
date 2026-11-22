/** Google Search shields. Red/amber from the on-device high-risk list immediately (no server call);
 * if the user enabled "Check search results", only result HOSTNAMES are sent to POST /lookup/hosts.
 * Each shield has "Check now" for a full scan. */
import { hostMatches, hostOf, t, type HostLookup, type Lang, type Tier } from "@hami/shared";
import { SEARCH, all, destinationOf, first } from "../selectors";
import { send } from "../lib/messages";
import { getLocalList, getSettings, type Settings } from "../lib/settings";
import { WIDGET_CSS, checkInto, dirFor, setShield, shieldButton } from "./overlay";

const MARK = "data-hami-done";
type Item = { host: string; url: string; button: HTMLButtonElement; root: ShadowRoot };
const items: Item[] = [];
let settings: Settings;
let lang: Lang;
let localHosts: string[] = [];
const looked = new Map<string, HostLookup>();

function isGoogle(host: string): boolean {
  return /(^|\.)google\.[a-z.]+$/.test(host) || host.endsWith("gstatic.com") || host.endsWith("googleadservices.com");
}

function collect(): Item[] {
  const found: Item[] = [];
  const areas = all<HTMLElement>(SEARCH.areas);
  const anchors = new Set<HTMLAnchorElement>();
  for (const area of areas) {
    for (const el of all<HTMLElement>(SEARCH.organicLink, area)) anchors.add((el.closest("a") ?? el) as HTMLAnchorElement);
    for (const el of all<HTMLAnchorElement>(SEARCH.adLink, area)) anchors.add(el);
  }
  for (const a of anchors) {
    if (!(a instanceof HTMLAnchorElement) || a.hasAttribute(MARK)) continue;
    const url = destinationOf(a);
    const host = url ? hostOf(url) : null;
    if (!url || !host || isGoogle(host)) continue;
    a.setAttribute(MARK, "1");
    const hostEl = document.createElement("span");
    hostEl.style.cssText = "all:initial;display:inline-block;position:relative;vertical-align:middle";
    const root = hostEl.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = WIDGET_CSS;
    const wrap = document.createElement("span");
    wrap.className = "w";
    wrap.dir = dirFor(lang);
    const button = shieldButton(null, lang);
    wrap.append(button);
    root.append(style, wrap);
    const title = first<HTMLElement>(SEARCH.titleOf, a);
    (title && a.contains(title) ? a : a).insertAdjacentElement("afterend", hostEl);
    const item = { host, url, button, root };
    button.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      togglePopover(item, wrap);
    });
    found.push(item);
  }
  return found;
}

function togglePopover(item: Item, wrap: HTMLElement): void {
  const existing = wrap.querySelector(".pop");
  if (existing) {
    existing.remove();
    return;
  }
  const pop = document.createElement("div");
  pop.className = "pop";
  const info = document.createElement("div");
  info.className = "muted";
  const tier = (item.button.dataset.tier || null) as Tier | null;
  const known = looked.get(item.host);
  info.textContent = localHosts.some((h) => hostMatches(item.host, h))
    ? t("shieldLocalHigh", lang)
    : tier && known ? `${t("shieldKnown", lang)} (${item.host})` : `${t("shieldUnknown", lang)} (${item.host})`;
  const body = document.createElement("div");
  const btn = document.createElement("button");
  btn.className = "btn";
  btn.textContent = t("checkNow", lang);
  btn.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    btn.disabled = true;
    await checkInto(body, item.url, lang, "search", null, (r) => setShield(item.button, r.tier, lang));
    btn.remove();
  });
  pop.append(info, btn, body);
  pop.addEventListener("click", (ev) => ev.stopPropagation());
  wrap.append(pop);
}

async function apply(newItems: Item[]): Promise<void> {
  if (!newItems.length) return;
  if (settings.localList) {
    for (const it of newItems) if (localHosts.some((h) => hostMatches(it.host, h))) setShield(it.button, "high_risk", lang, t("shieldLocalHigh", lang));
  }
  if (!settings.checkSearchResults) return;
  const hosts = [...new Set(newItems.map((i) => i.host))].filter((h) => !looked.has(h));
  if (!hosts.length) return;
  const res = await send<Record<string, HostLookup>>({ type: "lookup", hosts });
  if (!res.ok) return;
  for (const [h, v] of Object.entries(res.data)) looked.set(h, v);
  for (const it of newItems) {
    const v = looked.get(it.host);
    if (v?.known && v.tier && it.button.dataset.tier !== "high_risk") setShield(it.button, v.tier, lang, t("shieldKnown", lang));
  }
}

async function main(): Promise<void> {
  settings = await getSettings();
  lang = settings.lang;
  localHosts = settings.localList ? (await getLocalList()).hosts : [];
  const run = () => {
    const fresh = collect();
    items.push(...fresh);
    void apply(fresh);
  };
  run();
  let timer: number | undefined;
  new MutationObserver(() => {
    clearTimeout(timer);
    timer = window.setTimeout(run, 400);
  }).observe(document.body, { childList: true, subtree: true });
  document.addEventListener("click", () => items.forEach((i) => i.root.querySelector(".pop")?.remove()));
}

void main();
