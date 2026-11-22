/** Investigator mode (off by default): full HAR of one tab via chrome.debugger, sanitized on the device.
 * Chrome shows a "being debugged" bar while recording. Never runs on sensitive or well-known sites. */
import { sanitizeHar, sha256Hex, type Har, type HarEntry, type HarHeader } from "@hami/shared";

interface Rec {
  url: string;
  started: string;
  entries: Map<string, HarEntry & { _t0?: number; _mime?: string }>;
}

const recordings = new Map<number, Rec>();
const TEXT_MIME = /(text\/|json|javascript|ecmascript|xml|svg)/i;
const MAX_BODY = 2_000_000;

function hdrs(h: Record<string, string> | undefined): HarHeader[] {
  return Object.entries(h ?? {}).map(([name, value]) => ({ name, value: String(value) }));
}

export function isRecording(tabId: number): boolean {
  return recordings.has(tabId);
}

export async function start(tabId: number, url: string): Promise<void> {
  if (recordings.has(tabId)) return;
  await chrome.debugger.attach({ tabId }, "1.3");
  await chrome.debugger.sendCommand({ tabId }, "Network.enable", { maxPostDataSize: 0 });
  recordings.set(tabId, { url, started: new Date().toISOString(), entries: new Map() });
  await chrome.tabs.reload(tabId); // capture the full page load
}

async function onEvent(source: chrome.debugger.Debuggee, method: string, params?: object): Promise<void> {
  const tabId = source.tabId;
  if (tabId === undefined) return;
  const rec = recordings.get(tabId);
  if (!rec || !params) return;
  const p = params as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  if (method === "Network.requestWillBeSent") {
    rec.entries.set(p.requestId, {
      startedDateTime: new Date((p.wallTime ?? Date.now() / 1000) * 1000).toISOString(), time: 0, _t0: p.timestamp,
      request: { method: p.request.method, url: p.request.url, headers: hdrs(p.request.headers), cookies: [],
                 queryString: [...new URL(p.request.url).searchParams].map(([name, value]) => ({ name, value })),
                 ...(p.request.hasPostData ? { postData: { mimeType: "", text: "[removed by sanitizer]" } } : {}) },
      response: { status: 0, headers: [], cookies: [], content: { mimeType: "" } },
      _resourceType: String(p.type ?? "other").toLowerCase(),
    });
  } else if (method === "Network.responseReceived") {
    const e = rec.entries.get(p.requestId);
    if (!e) return;
    e.response.status = p.response.status;
    e.response.statusText = p.response.statusText;
    e.response.headers = hdrs(p.response.headers);
    e.response.content.mimeType = p.response.mimeType ?? "";
    e._mime = p.response.mimeType ?? "";
  } else if (method === "Network.loadingFinished") {
    const e = rec.entries.get(p.requestId);
    if (!e) return;
    e.time = e._t0 ? Math.round((p.timestamp - e._t0) * 1000) : 0;
    e.response.content.size = p.encodedDataLength;
    if (TEXT_MIME.test(e._mime ?? "") && p.encodedDataLength < MAX_BODY) {
      try {
        const body = (await chrome.debugger.sendCommand({ tabId }, "Network.getResponseBody", { requestId: p.requestId })) as
          { body: string; base64Encoded: boolean };
        e.response.content.text = body.body;
        if (body.base64Encoded) e.response.content.encoding = "base64";
      } catch {
        /* body no longer available */
      }
    }
  } else if (method === "Network.loadingFailed") {
    const e = rec.entries.get(p.requestId);
    if (e) e.response.statusText = `failed: ${p.errorText}`;
  } else if (method === "Network.webSocketCreated") {
    rec.entries.set(`ws-${p.requestId}`, {
      startedDateTime: new Date().toISOString(), time: 0,
      request: { method: "GET", url: p.url, headers: [], cookies: [], queryString: [] },
      response: { status: 101, headers: [], cookies: [], content: { mimeType: "websocket" } }, _resourceType: "websocket",
    });
  }
}

chrome.debugger.onEvent.addListener((s, m, p) => void onEvent(s, m, p));
chrome.debugger.onDetach.addListener((s) => {
  if (s.tabId !== undefined) recordings.delete(s.tabId);
});

function toBase64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

export interface SavedEvidence {
  filename: string;
  sha256: string;
  entries: number;
  harText: string;
  pageUrl: string;
}

/** Build + sanitize the HAR on the device, stop recording, download it as .har. */
export async function save(tabId: number): Promise<SavedEvidence> {
  const rec = recordings.get(tabId);
  if (!rec) throw new Error("this tab is not being recorded");
  recordings.delete(tabId);
  try {
    await chrome.debugger.detach({ tabId });
  } catch {
    /* already detached */
  }
  const entries = [...rec.entries.values()].map(({ _t0, _mime, ...e }) => { void _t0; void _mime; return e as HarEntry; });
  const har: Har = { log: { version: "1.2", creator: { name: "Hami investigator mode", version: "1.0" },
                            pages: [{ id: "page_1", startedDateTime: rec.started, title: rec.url, pageTimings: {} }], entries } };
  const clean = sanitizeHar(har);
  const harText = JSON.stringify(clean);
  const sha256 = await sha256Hex(harText);
  const host = new URL(rec.url).hostname.replace(/[^a-z0-9.-]/gi, "_");
  const filename = `hami-evidence-${host}-${new Date().toISOString().replace(/[:.]/g, "-")}.har`;
  const b64 = toBase64(new TextEncoder().encode(harText));
  await chrome.downloads.download({ url: `data:application/json;base64,${b64}`, filename, saveAs: false });
  return { filename, sha256, entries: entries.length, harText, pageUrl: rec.url };
}
