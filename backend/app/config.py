"""Runtime settings, read from environment variables (and an optional .env file).

Kept dependency-free on purpose: a tiny .env parser instead of pydantic-settings.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Real environment variables win over .env values.
        os.environ.setdefault(key, value)


_load_dotenv(REPO_DIR / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [p.strip() for p in os.environ.get(name, default).split(",") if p.strip()]


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("HAMI_DATA_DIR", str(BACKEND_DIR / "storage"))))
    models_dir: Path = field(default_factory=lambda: Path(_env("HAMI_MODELS_DIR", str(BACKEND_DIR / "models"))))
    private_dir: Path = field(default_factory=lambda: Path(_env("HAMI_PRIVATE_DIR", str(REPO_DIR / "data" / "private"))))
    processed_dir: Path = field(default_factory=lambda: Path(_env("HAMI_PROCESSED_DIR", str(REPO_DIR / "data" / "processed"))))

    reviewer_token: str = field(default_factory=lambda: _env("HAMI_REVIEWER_TOKEN", ""))
    public_base_url: str = field(default_factory=lambda: _env("HAMI_PUBLIC_BASE_URL", "http://localhost:8000"))

    # Capture limits (safety rules, section 2).
    capture_timeout_s: float = field(default_factory=lambda: _env_float("CAPTURE_TIMEOUT_S", 20.0))
    capture_max_requests: int = field(default_factory=lambda: _env_int("CAPTURE_MAX_REQUESTS", 150))
    capture_max_body_bytes: int = field(default_factory=lambda: _env_int("CAPTURE_MAX_BODY_BYTES", 1_500_000))
    capture_max_total_bytes: int = field(default_factory=lambda: _env_int("CAPTURE_MAX_TOTAL_BYTES", 25_000_000))
    capture_concurrency: int = field(default_factory=lambda: _env_int("CAPTURE_CONCURRENCY", 2))
    # Private/loopback targets are refused unless the host is allow-listed (test sites).
    capture_allow_hosts: list[str] = field(default_factory=lambda: _env_list("CAPTURE_ALLOW_HOSTS", "localhost,*.localhost"))
    capture_allow_private: bool = field(default_factory=lambda: _env_bool("CAPTURE_ALLOW_PRIVATE", False))
    scan_cache_ttl_s: int = field(default_factory=lambda: _env_int("SCAN_CACHE_TTL_S", 6 * 3600))

    # API rate limits (requests per minute).
    rate_scans_per_min: int = field(default_factory=lambda: _env_int("RATE_SCANS_PER_MIN", 12))
    rate_lookup_per_min: int = field(default_factory=lambda: _env_int("RATE_LOOKUP_PER_MIN", 60))
    rate_default_per_min: int = field(default_factory=lambda: _env_int("RATE_DEFAULT_PER_MIN", 120))
    rate_ip_multiplier: int = field(default_factory=lambda: _env_int("RATE_IP_MULTIPLIER", 3))

    cors_extra_origins: list[str] = field(default_factory=lambda: _env_list("CORS_EXTRA_ORIGINS", "http://localhost:8081,http://localhost:19006"))

    # Discovery worker.
    discovery_poll_s: int = field(default_factory=lambda: _env_int("DISCOVERY_POLL_S", 600))
    discovery_query_gap_s: float = field(default_factory=lambda: _env_float("DISCOVERY_QUERY_GAP_S", 20.0))
    discovery_capture_gap_s: float = field(default_factory=lambda: _env_float("DISCOVERY_CAPTURE_GAP_S", 30.0))
    discovery_max_captures_per_cycle: int = field(default_factory=lambda: _env_int("DISCOVERY_MAX_CAPTURES_PER_CYCLE", 5))
    discovery_max_age_days: int = field(default_factory=lambda: _env_int("DISCOVERY_MAX_AGE_DAYS", 7))
    discovery_enabled: bool = field(default_factory=lambda: _env_bool("DISCOVERY_ENABLED", True))

    # Bulk captures of approved URL lists.
    bulk_capture_gap_s: float = field(default_factory=lambda: _env_float("BULK_CAPTURE_GAP_S", 5.0))

    testsite_base_url: str = field(default_factory=lambda: _env("TESTSITE_BASE_URL", "http://site-a.localhost:8100"))
    testsite_port: int = field(default_factory=lambda: _env_int("TESTSITE_PORT", 8100))
    run_testsites: bool = field(default_factory=lambda: _env_bool("RUN_TESTSITES", False))

    static_authorized_dirs: list[str] = field(default_factory=lambda: _env_list("STATIC_AUTHORIZED_DIRS", str(REPO_DIR / "testsites" / "static_files")))

    @property
    def db_path(self) -> Path:
        return Path(_env("HAMI_DB_PATH", str(self.data_dir / "hami.sqlite3")))

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.artifacts_dir, self.models_dir):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
