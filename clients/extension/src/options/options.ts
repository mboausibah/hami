import { HamiApi, normalizeBaseUrl, t, type Lang } from "@hami/shared";
import { send } from "../lib/messages";
import { getDeviceId, getLocalList, getSettings, saveSettings, type LocalList } from "../lib/settings";
import { applyLang } from "../lib/ui";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
let lang: Lang = "en";

function showList(l: LocalList): void {
  const when = l.syncedAt ? new Date(l.syncedAt).toLocaleString(lang === "ar" ? "ar-AE" : "en-AE") : "-";
  $("list-status").textContent = `${l.hosts.length} ${t("hosts", lang)} · ${t("version", lang)} ${l.version} · ${when}` +
    (l.error ? ` · ${t("serverError", lang)} (${l.error})` : "");
}

async function init(): Promise<void> {
  const s = await getSettings();
  lang = s.lang;
  applyLang(lang);
  $<HTMLInputElement>("serverUrl").value = s.serverUrl;
  $<HTMLSelectElement>("lang").value = s.lang;
  $<HTMLInputElement>("localList").checked = s.localList;
  $<HTMLInputElement>("checkSearchResults").checked = s.checkSearchResults;
  $<HTMLInputElement>("autoCheck").checked = s.autoCheck;
  showList(await getLocalList());

  $("lang").addEventListener("change", () => applyLang($<HTMLSelectElement>("lang").value as Lang));
  $("test").addEventListener("click", async () => {
    const out = $("test-result");
    try {
      const h = await new HamiApi(normalizeBaseUrl($<HTMLInputElement>("serverUrl").value), await getDeviceId()).health();
      out.className = "ok";
      out.textContent = `${t("connected", lang)} · ${t("model", lang)} ${h.model_version ?? "-"}`;
    } catch (e) {
      out.className = "err";
      out.textContent = `${t("serverError", lang)}: ${(e as Error).message}`;
    }
  });
  $("sync").addEventListener("click", async () => {
    const res = await send<LocalList>({ type: "syncNow" });
    if (res.ok) showList(res.data);
  });
  $("save").addEventListener("click", async () => {
    let serverUrl: string;
    try {
      serverUrl = normalizeBaseUrl($<HTMLInputElement>("serverUrl").value);
    } catch (e) {
      $("saved").className = "err";
      $("saved").textContent = (e as Error).message;
      return;
    }
    const next = await saveSettings({
      serverUrl,
      lang: $<HTMLSelectElement>("lang").value as Lang,
      localList: $<HTMLInputElement>("localList").checked,
      checkSearchResults: $<HTMLInputElement>("checkSearchResults").checked,
      autoCheck: $<HTMLInputElement>("autoCheck").checked,
    });
    lang = next.lang;
    applyLang(lang);
    $("saved").className = "ok";
    $("saved").textContent = t("saved", lang);
    const res = await send<LocalList>({ type: "syncNow" });
    if (res.ok) showList(res.data);
  });
}

void init();
