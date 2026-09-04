#!/usr/bin/env python3
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt

MAX_BODY_BYTES = 4096
COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{40}")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
ASSIGNMENT_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,100}")
RESULT_STATUSES = {"PASSED", "FAILED", "ERROR"}
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
OIDC_JWKS = jwt.PyJWKClient(f"{OIDC_ISSUER}/.well-known/jwks")


def positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{name} must be a positive integer")
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if result < 1:
        raise ValueError(f"{name} must be a positive integer")
    return result


def validate_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")

    result = {
        "repository": payload.get("repository"),
        "commit": payload.get("commit"),
        "assignment": payload.get("assignment"),
        "assignment_sha": payload.get("assignment_sha"),
        "status": payload.get("status"),
        "run_id": positive_int(payload.get("run_id"), "run_id"),
        "run_number": positive_int(payload.get("run_number"), "run_number"),
        "run_attempt": positive_int(payload.get("run_attempt"), "run_attempt"),
    }

    if not isinstance(result["repository"], str) or not REPOSITORY_PATTERN.fullmatch(
        result["repository"]
    ):
        raise ValueError("repository must be an owner/name pair")
    if not isinstance(result["commit"], str) or not COMMIT_PATTERN.fullmatch(result["commit"]):
        raise ValueError("commit must be a 40-character SHA")
    if not isinstance(result["assignment"], str) or not ASSIGNMENT_PATTERN.fullmatch(
        result["assignment"]
    ):
        raise ValueError("assignment must be a name")
    if not isinstance(result["assignment_sha"], str) or not COMMIT_PATTERN.fullmatch(
        result["assignment_sha"]
    ):
        raise ValueError("assignment_sha must be a 40-character SHA")
    if result["status"] not in RESULT_STATUSES:
        raise ValueError("status must be PASSED, FAILED, or ERROR")

    return result


def decode_oidc_token(token, audience):
    signing_key = OIDC_JWKS.get_signing_key_from_jwt(token)
    required_claims = [
        "aud",
        "event_name",
        "exp",
        "iat",
        "iss",
        "job_workflow_ref",
        "job_workflow_sha",
        "ref",
        "repository",
        "repository_visibility",
        "run_attempt",
        "run_id",
        "run_number",
        "runner_environment",
        "sha",
    ]
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=OIDC_ISSUER,
        options={"require": required_claims},
    )


def configured_values(name):
    values = {value.strip() for value in os.environ.get(name, "").split(",") if value.strip()}
    if not values:
        raise RuntimeError(f"{name} must be configured")
    return values


def verify_repository_source(repository):
    source_repository = os.environ.get("ALLOWED_SOURCE_REPOSITORY", "")
    if not REPOSITORY_PATTERN.fullmatch(source_repository):
        raise RuntimeError("ALLOWED_SOURCE_REPOSITORY must be configured")

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "spring-seminar-judge",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_API_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    request = Request(f"https://api.github.com/repos/{repository}", headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            metadata = json.loads(response.read())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("failed to verify repository") from error

    if (
        not metadata.get("fork")
        or metadata.get("source", {}).get("full_name", "").lower()
        != source_repository.lower()
    ):
        raise PermissionError("repository is not an allowed fork")


def authenticate_request(authorization, result):
    audience = os.environ.get("OIDC_AUDIENCE")
    workflow_ref = os.environ.get("ALLOWED_WORKFLOW_REF")
    if not audience or not workflow_ref:
        raise RuntimeError("OIDC_AUDIENCE and ALLOWED_WORKFLOW_REF must be configured")

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise PermissionError("missing bearer token")

    claims = decode_oidc_token(authorization[len(prefix):], audience)
    if (
        result["assignment"] not in configured_values("ALLOWED_ASSIGNMENTS")
        or claims["job_workflow_sha"] not in configured_values("ALLOWED_WORKFLOW_SHAS")
        or claims["job_workflow_ref"] != workflow_ref
        or claims["repository"] != result["repository"]
        or claims["sha"].lower() != result["commit"].lower()
        or positive_int(claims["run_id"], "run_id") != result["run_id"]
        or positive_int(claims["run_number"], "run_number") != result["run_number"]
        or positive_int(claims["run_attempt"], "run_attempt") != result["run_attempt"]
        or claims["ref"] != os.environ.get("ALLOWED_REF", "refs/heads/main")
        or claims["event_name"] != "push"
        or claims["repository_visibility"] != "public"
        or claims["runner_environment"] != "github-hosted"
    ):
        raise PermissionError("token claims do not match the grading result")

    verify_repository_source(result["repository"])


def save_result(result):
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY")
    if not supabase_url.startswith("https://") or not secret_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be configured")

    row = {
        "repository": result["repository"],
        "assignment": result["assignment"],
        "assignment_sha": result["assignment_sha"],
        "commit_sha": result["commit"],
        "status": result["status"],
        "workflow_run_id": result["run_id"],
        "run_number": result["run_number"],
        "run_attempt": result["run_attempt"],
    }
    request = Request(
        f"{supabase_url}/rest/v1/results"
        "?on_conflict=repository,assignment,workflow_run_id,run_attempt",
        data=json.dumps(row).encode(),
        headers={
            "apikey": secret_key,
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates,return=minimal",
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        if response.status not in (200, 201, 204):
            raise RuntimeError("Supabase rejected the result")


def load_results():
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY")
    if not supabase_url.startswith("https://") or not secret_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be configured")

    query = urlencode(
        {
            "select": "repository,assignment,commit_sha,status,run_number,run_attempt,graded_at",
            "order": "graded_at.desc",
            "limit": 100,
        }
    )
    request = Request(
        f"{supabase_url}/rest/v1/results?{query}",
        headers={"apikey": secret_key},
    )
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("Supabase rejected the query")
        return json.loads(response.read())


class ResultHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/results", "/api/results"):
            self.send_json(404, {"error": "not found"})
            return

        try:
            results = load_results()
        except (OSError, RuntimeError, json.JSONDecodeError):
            self.send_json(500, {"error": "failed to load results"})
            return

        self.send_json(200, {"results": results})

    def do_POST(self):
        if self.path not in ("/results", "/api/results"):
            self.send_json(404, {"error": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if not 0 < content_length <= MAX_BODY_BYTES:
                raise ValueError("request body must be between 1 and 4096 bytes")
            result = validate_request(json.loads(self.rfile.read(content_length)))
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
            return

        try:
            authenticate_request(self.headers.get("Authorization", ""), result)
        except (PermissionError, jwt.PyJWTError):
            self.send_json(401, {"error": "invalid OIDC token"})
            return
        except RuntimeError as error:
            self.send_json(500, {"error": str(error)})
            return

        try:
            save_result(result)
        except (OSError, RuntimeError):
            self.send_json(500, {"error": "failed to store result"})
            return

        self.send_json(201, {"recorded": True})

    def send_json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    print(f"listening on http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), ResultHandler).serve_forever()
