/** Helpers shared by the popup, result page and options page. */
import { HamiApi, dirOf, t, type Lang, type ScanResult } from "@hami/shared";
import { CARD_CSS, renderCard } from "./card";
import { send } from "./messages";
import { getDeviceId, getSettings, getWatchMap } from "./settings";

export function applyLang(lang: Lang): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = dirOf(lang);
  document.querySelectorAll<HTMLElement>("[data-t]").forEach((e) => {
    e.textContent = t(e.dataset.t as Parameters<typeof t>[0], lang);
  });
}

export function injectCardCss(): void {
  const s = document.createElement("style");
  s.textContent = CARD_CSS;
  document.head.append(s);
}

export async function resolver(): Promise<(p: string) => string> {
  const s = await getSettings();
  const client = new HamiApi(s.serverUrl, await getDeviceId());
  return (p: string) => client.resolve(p);
}

export function errorText(err: { error: string; status?: number }, lang: Lang): string {
  if (err.status === 429) return t("rateLimited", lang);
  if (err.status === 0 || err.status === undefined) return `${t("serverError", lang)} (${err.error})`;
  return `${t("serverError", lang)}: ${err.error}`;
}

/** Render a result with a working watch toggle. */
export async function showResult(container: HTMLElement, r: ScanResult, lang: Lang, compact = false): Promise<void> {
  const watches = await getWatchMap();
  renderCard(container, r, {
    lang,
    compact,
    resolve: await resolver(),
    watching: !!watches[String(r.scan_id)] || Object.values(watches).some((w) => w.host === r.host),
    onWatchToggle: async (on) => {
      const res = on
        ? await send({ type: "watch", scanId: r.scan_id, key: r.access_key, host: r.host })
        : await send({ type: "unwatch", scanId: r.scan_id });
      return res.ok;
    },
  });
}
