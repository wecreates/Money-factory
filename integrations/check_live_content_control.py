"""Read-only runtime evidence for the existing free Content Control service.

No credentials, dispatch, generation, publication or readiness promotion.
Run from repository root; stdout is a JSON observation, including HTTP failures.
"""
import concurrent.futures
import datetime
import hashlib
import json
import urllib.error
import urllib.request

BASE = "https://content-control-render-worker.onrender.com"


def observe(path, headers=None):
    try:
        request = urllib.request.Request(BASE + path, headers=headers or {})
        try:
            response = urllib.request.urlopen(request, timeout=55)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read(16 * 1024 * 1024 + 1)
            if len(body) > 16 * 1024 * 1024:
                return {"path": path, "error": "RESPONSE_TOO_LARGE"}
            result = {"path": path, "http_status": response.status,
                      "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                      "content_type": response.headers.get("Content-Type"),
                      "content_range": response.headers.get("Content-Range")}
            if "application/json" in (result["content_type"] or ""):
                result["body"] = json.loads(body)
            return result
    except (OSError, ValueError) as error:
        return {"path": path, "error": type(error).__name__}


def main():
    paths = ["/health", "/api/integrations/status", "/api/production/v2",
             "/v2/draft/media", "/media", "/captions"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        observations = list(executor.map(observe, paths))
    observations.append(observe("/media", {"Range": "bytes=0-1023"}))
    health = observations[0].get("body", {})
    media = observations[4]
    print(json.dumps({"schema_version": 1,
        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_url": BASE, "production_ready": False,
        "scope": "Read-only live observations; old artifact playback does not prove current generation acceptance",
        "accepted_media_hash_matches_health": media.get("http_status") == 200 and
            media.get("sha256") == health.get("expectedSha256") == health.get("actualSha256"),
        "observations": observations}, indent=2))


if __name__ == "__main__":
    main()
