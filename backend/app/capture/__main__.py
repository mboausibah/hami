import json, os, sys
from app.capture import capture
r = capture(sys.argv[1] if len(sys.argv) > 1 else "https://example.com")
print(json.dumps({"status": r.status, "final_url": r.final_url, "http": r.http_status, "steps": [s.action for s in r.steps], "requests": r.request_count, "har_entries": len((r.har or {}).get("log", {}).get("entries", [])), "blocked": r.blocked, "error": r.error, "log": [a["action"] for a in r.action_log]}, indent=1))
