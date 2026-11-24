/** Response types of the Hami API (mirrors backend/app/pipeline.py and app/services.py). */

export type Tier = "high_risk" | "caution" | "no_strong_signals" | "insufficient_evidence";
export type Lang = "ar" | "en";
export type SourceType = "search" | "maps" | "sms" | "whatsapp" | "manual" | "extension" | "discovery";
export type Bilingual = { en: string; ar: string };
export type BilingualList = { en: string[]; ar: string[] };

export interface Clue {
  type: string;
  text: Bilingual;
  excerpt: string | null;
  excerpt_lang: string | null;
  obs_id: number | null;
  screenshot_artifact_id: number | null;
  screenshot_url: string | null;
}

export interface Artifact {
  artifact_id: number;
  kind: "har" | "html" | "screenshot" | "action_log" | "analysis" | "model_text";
  sha256: string;
  action_step: number | null;
  action: string | null;
  captured_at: string;
  size_bytes: number;
  url: string | null;
}

export interface ScanResult {
  /** Evidence still being gathered (e.g. "domain_age"): such a result is not reused for long. */
  pending?: string[];
  scan_id: number;
  access_key: string;
  url: string;
  final_url: string | null;
  host: string;
  source_type: SourceType | "import";
  listing_name: string | null;
  status: "pending" | "capturing" | "analyzing" | "done" | "failed";
  submitted_at: string;
  captured_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  page_lang: string | null;
  capture_mode: "live" | "stored";
  capture_status: string | null;
  cached: boolean;
  tier: Tier | null;
  tier_label?: Bilingual;
  headline?: Bilingual;
  score?: number | null;
  clues: Clue[];
  what_to_do?: BilingualList;
  not_checked?: BilingualList;
  identity_check?: "match" | "mismatch" | "unclear" | "not_checked";
  model_version?: string | null;
  rules_fired?: string[];
  artifacts: Artifact[];
  review: { label: string; behavior_tags: string[]; reviewed_at: string } | null;
  live_failure?: string | null;
}

export interface HostLookup {
  known: boolean;
  tier: Tier | null;
  source?: "reviewed" | "assessment";
  reviewed_at?: string;
  assessed_at?: string;
}

export interface Watch {
  watch_id: string;
  scan_id: number;
  host: string;
  created_at: string;
  tier?: Tier | null;
}

export interface HamiAlert {
  alert_id: number;
  watched_host: string;
  related_host: string | null;
  related_host_defanged: string | null;
  related_tier: Tier | null;
  reason: Bilingual;
  status: "approved" | "withdrawn";
  created_at: string;
  sent_at: string | null;
  withdrawn: boolean;
  withdrawn_at: string | null;
  withdrawn_reason: string | null;
}

export interface HighRiskList {
  version: number;
  count: number;
  hosts: string[];
}

export interface Health {
  status: string;
  model_version: string | null;
  scans: number;
  reviewer_token_configured: boolean;
}

/** Structure of a page as rendered in the user's browser (computed on the device; see extension lib/pagesignals.ts).
 * Never contains field values, query strings or cookies. */
export interface PageSignals {
  page_url: string;
  title: string;
  lang: string;
  text: string;
  paths: string[];
  images: string[];
  fields: { type: string; name: string; placeholder: string; label: string; autocomplete: string;
            required: boolean; readonly: boolean; has_value: boolean }[];
  identity_links: boolean;
  h5_shell: boolean;
}
