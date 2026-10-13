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


def object_body(observation):
    """Only successful object JSON is usable evidence; errors never imply readiness."""
    body = observation.get("body")
    return body if observation.get("http_status") == 200 and isinstance(body, dict) else {}


def strings(value):
    return value if isinstance(value, list) and all(isinstance(x, str) for x in value) else None


def social_summary(runtime_observation, links_observation, status_observation):
    runtime = object_body(runtime_observation)
    links = object_body(links_observation)
    account_status = object_body(status_observation)
    bootstrap = runtime.get("storage_bootstrap")
    bootstrap = bootstrap if isinstance(bootstrap, dict) else {}
    health = runtime.get("storage_health")
    health = health if isinstance(health, dict) else {}
    configuration = runtime.get("authorization_configuration")
    configuration = configuration if isinstance(configuration, dict) else {}
    missing = {name: strings(group.get("missing_configuration"))
               for name, group in configuration.items() if isinstance(group, dict)}
    references = links.get("references")
    valid_references = isinstance(references, list) and all(
        isinstance(ref, dict) and isinstance(ref.get("reference_checks"), list)
        and len(ref["reference_checks"]) > 0
        and all(isinstance(check, dict) for check in ref["reference_checks"])
        for ref in references)
    checks = [check for ref in references for check in ref["reference_checks"]] if valid_references else []
    verified = sum(check.get("evidence_verified") is True and
                   check.get("status") == "verified_repository_evidence" for check in checks)
    connection_health = account_status.get("connection_health")
    connections = connection_health if isinstance(connection_health, list) else []
    connection_observations = [{key: item[key] for key in
        ("platform", "status", "connected", "last_read_verified_at") if key in item}
        for item in connections if isinstance(item, dict)]
    publication_disabled = all(body.get("publication_enabled") is False
                               for body in (runtime, links, account_status))
    return {
        "runtime_status": runtime.get("status", "UNKNOWN"),
        "runtime_response_valid": bool(runtime),
        "publication_policy": "REPORTED_DISABLED" if publication_disabled else "UNVERIFIED_OR_UNSAFE",
        "external_writes_reported_disabled": runtime.get("external_writes_enabled") is False,
        "policy_scope": "Read-only reported flags; this observation does not test write enforcement",
        "storage": {
            "mode": runtime.get("configured_storage_mode", "UNKNOWN"),
            "startup_read_verified": bootstrap.get("read_verified") is True,
            "startup_checked_at": bootstrap.get("checked_at"),
            "health_status": health.get("status", "UNKNOWN"),
            "live_database_available": health.get("live_database_checked") is True and health.get("availability_verified") is True,
            "durability_verified_by_this_monitor": False,
            "expires_at": runtime.get("storage_expires_at"),
            "operations_blocked": health.get("operations_blocked") if isinstance(health.get("operations_blocked"), bool) else None,
            "scope": "Startup reads are historical; no database read or restart test is performed by this monitor",
        },
        "missing_storage_configuration": strings(runtime.get("missing_configuration")),
        "missing_authorization_configuration": missing,
        "worker_reported_running": runtime.get("worker_running") is True,
        "oauth_routes_reported_enabled": runtime.get("oauth_routes_enabled") is True,
        "connection_observations": connection_observations,
        "connections_live_verified_by_this_monitor": False,
        "connection_scope": "Repository observations only; no authenticated provider request performed",
        "evidence_routing": {
            "status": ("VERIFIED_REPOSITORY_REFERENCES" if checks and verified == len(checks)
                       else "INVALID_REFERENCES" if checks else "NO_VERIFIED_REFERENCES"),
            "response_schema_valid": valid_references,
            "reference_count": len(checks), "verified_reference_count": verified,
            "runtime_routing_verified": False, "revenue_verified": False,
            "scope": "Repository reference integrity only; not execution, full video analysis or revenue",
        },
    }


def build_report(observations):
    by_path = {item["path"]: item for item in observations if item.get("path") != "/media"}
    media = next((item for item in observations if item.get("path") == "/media" and item.get("http_status") == 200), {})
    health = object_body(by_path.get("/health", {}))
    return {"schema_version": 2,
        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_url": BASE, "production_ready": False,
        "scope": "Read-only live observations; old artifact playback does not prove current generation acceptance",
        "accepted_media_hash_matches_health": bool(media.get("sha256")) and media.get("http_status") == 200 and
            media.get("sha256") == health.get("expectedSha256") == health.get("actualSha256"),
        "social_integration": social_summary(by_path.get("/api/social/runtime", {}),
            by_path.get("/api/social/project-links", {}), by_path.get("/api/social/status", {})),
        "observations": observations}


def main():
    paths = ["/health", "/api/integrations/status", "/api/production/v2",
             "/v2/draft/media", "/media", "/captions", "/api/social/runtime",
             "/api/social/project-links", "/api/social/status"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        observations = list(executor.map(observe, paths))
    observations.append(observe("/media", {"Range": "bytes=0-1023"}))
    print(json.dumps(build_report(observations), indent=2))


if __name__ == "__main__":
    main()
