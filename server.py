#!/usr/bin/env python3
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import jwt

MAX_BODY_BYTES = 4096
COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{40}")
ASSIGNMENT_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,100}")
GRADE_SCRIPT = Path(__file__).with_name("grade.sh")
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
OIDC_JWKS = jwt.PyJWKClient(f"{OIDC_ISSUER}/.well-known/jwks")


def validate_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")

    repository = payload.get("repository")
    commit = payload.get("commit")
    assignment = payload.get("assignment")

    if not isinstance(repository, str) or github_repository_name(repository) is None:
        raise ValueError("repository must be a GitHub HTTPS URL")
    if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("commit must be a 40-character SHA")
    if not isinstance(assignment, str) or not ASSIGNMENT_PATTERN.fullmatch(assignment):
        raise ValueError("assignment must be a tag or commit name")

    return repository, commit, assignment


def github_repository_name(repository):
    try:
        url = urlsplit(repository)
        parts = [part for part in url.path.split("/") if part]
        if not (
            url.scheme == "https"
            and url.hostname == "github.com"
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and len(parts) == 2
        ):
            return None
        return f"{parts[0]}/{parts[1].removesuffix('.git')}"
    except ValueError:
        return None


def decode_oidc_token(token, audience):
    signing_key = OIDC_JWKS.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=OIDC_ISSUER,
        options={"require": ["aud", "exp", "iat", "iss", "repository", "repository_owner", "ref", "sha"]},
    )


def authenticate_request(authorization, repository, commit, assignment):
    audience = os.environ.get("OIDC_AUDIENCE")
    allowed_owner = os.environ.get("ALLOWED_REPOSITORY_OWNER")
    allowed_assignments = os.environ.get("ALLOWED_ASSIGNMENTS")
    if not audience or not allowed_owner or not allowed_assignments:
        raise RuntimeError(
            "OIDC_AUDIENCE, ALLOWED_REPOSITORY_OWNER, and ALLOWED_ASSIGNMENTS must be configured"
        )

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise PermissionError("missing bearer token")

    claims = decode_oidc_token(authorization[len(prefix):], audience)
    repository_name = github_repository_name(repository)
    allowed_ref = os.environ.get("ALLOWED_REF", "refs/heads/main")
    assignments = {value.strip() for value in allowed_assignments.split(",")}
    if (
        assignment not in assignments
        or claims["repository"] != repository_name
        or claims["repository_owner"] != allowed_owner
        or claims["sha"].lower() != commit.lower()
        or claims["ref"] != allowed_ref
    ):
        raise PermissionError("token claims do not match the grading request")


def run_grading(repository, commit, assignment):
    environment = os.environ.copy()
    environment["UPSTREAM_REF"] = assignment
    return subprocess.run(
        [GRADE_SCRIPT, repository, commit],
        env=environment,
        timeout=600,
        check=False,
    ).returncode


class GradingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/gradings":
            self.send_json(404, {"error": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if not 0 < content_length <= MAX_BODY_BYTES:
                raise ValueError("request body must be between 1 and 4096 bytes")
            payload = json.loads(self.rfile.read(content_length))
            repository, commit, assignment = validate_request(payload)
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
            return

        try:
            authenticate_request(
                self.headers.get("Authorization", ""), repository, commit, assignment
            )
        except (PermissionError, jwt.PyJWTError):
            self.send_json(401, {"error": "invalid OIDC token"})
            return
        except RuntimeError as error:
            self.send_json(500, {"error": str(error)})
            return

        try:
            returncode = run_grading(repository, commit, assignment)
        except subprocess.TimeoutExpired:
            self.send_json(504, {"status": "ERROR", "error": "grading timed out"})
            return

        if returncode == 0:
            self.send_json(200, {"status": "PASSED"})
        elif returncode == 1:
            self.send_json(200, {"status": "FAILED"})
        else:
            self.send_json(500, {"status": "ERROR", "error": "grading runner failed"})

    def send_json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    print(f"listening on http://{host}:{port}", flush=True)
    HTTPServer((host, port), GradingHandler).serve_forever()
