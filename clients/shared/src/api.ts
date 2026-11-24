import { normalizeBaseUrl } from "./config";
import type { HamiAlert, Health, HighRiskList, HostLookup, Lang, PageSignals, ScanResult, SourceType, Watch } from "./types";

export class HamiApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "HamiApiError";
  }
}

export interface ScanOptions {
  sourceType?: SourceType;
  listingName?: string | null;
  lang?: Lang;
  force?: boolean;
  /** Page structure from the user's browser (paths, field descriptors, image names; no values). */
  pageSignals?: PageSignals | null;
}

/** Typed client for the Hami API. The device ID is sent only as a rate-limit key and for watches. */
export class HamiApi {
  readonly baseUrl: string;

  constructor(
    baseUrl: string,
    private readonly deviceId: string,
    private readonly timeoutMs = 75_000,
  ) {
    this.baseUrl = normalizeBaseUrl(baseUrl);
  }

  /** Absolute URL for a path returned by the API (e.g. screenshot URLs). */
  resolve(path: string): string {
    return /^https?:\/\//i.test(path) ? path : this.baseUrl + path;
  }

  private async request<T>(method: string, path: string, body?: unknown, timeoutMs = this.timeoutMs): Promise<T> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(this.baseUrl + path, {
        method,
        headers: { "Content-Type": "application/json", "X-Device-Id": this.deviceId },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        let detail = res.statusText;
        try {
          const j = (await res.json()) as { detail?: unknown };
          if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        } catch {
          /* non-JSON error body */
        }
        throw new HamiApiError(detail, res.status);
      }
      return (await res.json()) as T;
    } catch (e) {
      if (e instanceof HamiApiError) throw e;
      if ((e as Error).name === "AbortError") throw new HamiApiError("timeout", 0);
      throw new HamiApiError((e as Error).message || "network error", 0);
    } finally {
      clearTimeout(timer);
    }
  }

  scan(url: string, opts: ScanOptions = {}): Promise<ScanResult> {
    return this.request<ScanResult>("POST", "/scans", {
      url,
      source_type: opts.sourceType ?? "extension",
      listing_name: opts.listingName || null,
      lang: opts.lang ?? "en",
      device_id: this.deviceId,
      force: opts.force ?? false,
      page_signals: opts.pageSignals ?? null,
    });
  }

  getScan(scanId: number, key: string): Promise<ScanResult> {
    return this.request<ScanResult>("GET", `/scans/${scanId}?k=${encodeURIComponent(key)}`);
  }

  /** Only hostnames are sent (never full URLs or search queries). */
  lookupHosts(hosts: string[]): Promise<{ results: Record<string, HostLookup> }> {
    return this.request("POST", "/lookup/hosts", { hosts: hosts.slice(0, 60) }, 15_000);
  }

  watch(scanId: number, key: string): Promise<Watch> {
    return this.request<Watch>("POST", "/watches", { scan_id: scanId, device_id: this.deviceId, k: key });
  }

  unwatch(watchId: string): Promise<{ deleted: boolean }> {
    return this.request("DELETE", `/watches/${encodeURIComponent(watchId)}?device_id=${encodeURIComponent(this.deviceId)}`);
  }

  watches(): Promise<{ watches: Watch[] }> {
    return this.request("GET", `/watches?device_id=${encodeURIComponent(this.deviceId)}`, undefined, 15_000);
  }

  alerts(): Promise<{ alerts: HamiAlert[] }> {
    return this.request("GET", `/alerts?device_id=${encodeURIComponent(this.deviceId)}`, undefined, 15_000);
  }

  highRiskHosts(): Promise<HighRiskList> {
    return this.request("GET", "/indicators/high-risk-hosts", undefined, 15_000);
  }

  /** Idle snapshot: resource URLs without query strings, types, statuses, timings + redacted visible text. */
  snapshot(body: {
    page_url: string;
    resources: { url: string; type: string; status: number | null; duration_ms: number | null; size: number | null }[];
    visible_text: string;
    lang: string;
    scan_id?: number;
    k?: string;
  }): Promise<ScanResult & { snapshot_id: number; linked_scan_id: number | null }> {
    return this.request("POST", "/snapshots", { ...body, device_id: this.deviceId }, 60_000);
  }

  /** Investigator evidence: a HAR already sanitized on the device, with the SHA-256 computed there. */
  uploadEvidence(body: { page_url: string; har_text: string; client_sha256: string; entries: number; scan_id?: number; k?: string }):
    Promise<ScanResult & { evidence_id: number; client_sha256: string; server_sha256: string; hash_match: boolean }> {
    return this.request("POST", "/evidence", { ...body, device_id: this.deviceId }, 120_000);
  }

  health(): Promise<Health> {
    return this.request("GET", "/health", undefined, 8_000);
  }
}
