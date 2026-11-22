/** Full result page: opened from the right-click menu (?url=...) or from "Open full result" (?scan=&k=). */
import { t, type Lang, type ScanResult, type SourceType } from "@hami/shared";
import { send } from "../lib/messages";
import { getSettings } from "../lib/settings";
import { applyLang, errorText, injectCardCss, showResult } from "../lib/ui";

const $ = (id: string) => document.getElementById(id)!;
let lang: Lang = "en";

async function scan(url: string, source: SourceType, listing: string | null, force: boolean): Promise<void> {
  $("status").className = "status";
  $("status").textContent = t("checking", lang);
  $("url").textContent = url;
  const res = await send<ScanResult>({ type: "scan", url, sourceType: source, listingName: listing, force });
  if (!res.ok) {
    $("status").className = "status err";
    $("status").textContent = errorText(res, lang);
    return;
  }
  history.replaceState(null, "", `?scan=${res.data.scan_id}&k=${encodeURIComponent(res.data.access_key)}`);
  await done(res.data);
}

async function done(r: ScanResult): Promise<void> {
  $("status").textContent = "";
  $("url").textContent = r.final_url ?? r.url;
  document.title = `Hami — ${r.tier_label?.[lang] ?? ""} — ${r.host}`;
  await showResult($("result"), r, lang);
  const re = $("recheck");
  re.hidden = false;
  re.onclick = () => void scan(r.url, "extension", r.listing_name, true);
}

async function init(): Promise<void> {
  injectCardCss();
  lang = (await getSettings()).lang;
  applyLang(lang);
  const q = new URLSearchParams(location.search);
  const scanId = Number(q.get("scan"));
  const key = q.get("k");
  if (scanId && key) {
    $("status").textContent = t("checking", lang);
    const res = await send<ScanResult>({ type: "getScan", scanId, key });
    if (res.ok) await done(res.data);
    else $("status").textContent = errorText(res, lang);
    return;
  }
  const url = q.get("url");
  if (url) await scan(url, (q.get("source") as SourceType) || "extension", q.get("listing"), false);
}

void init();
