import json
import threading
import time
import unittest
from http.server import HTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import server

COMMIT = "0123456789abcdef0123456789abcdef01234567"
WORKFLOW_REF = (
    "WaffleStudio24-5/spring-seminar-judge/.github/workflows/grade.yml@refs/heads/main"
)


def result_payload():
    return {
        "repository": "student/assignment",
        "commit": COMMIT,
        "assignment": "main",
        "assignment_sha": COMMIT,
        "status": "PASSED",
        "run_id": "123",
        "run_number": "4",
        "run_attempt": "1",
    }


def oidc_claims():
    return {
        "repository": "student/assignment",
        "sha": COMMIT,
        "ref": "refs/heads/main",
        "event_name": "push",
        "repository_visibility": "public",
        "runner_environment": "github-hosted",
        "job_workflow_ref": WORKFLOW_REF,
        "run_id": "123",
        "run_number": "4",
        "run_attempt": "1",
    }


class ServerTest(unittest.TestCase):
    def setUp(self):
        patch("server.authenticate_request").start()
        self.save_result = patch("server.save_result").start()
        self.load_results = patch("server.load_results", return_value=[{"status": "PASSED"}]).start()
        self.addCleanup(patch.stopall)
        self.httpd = HTTPServer(("127.0.0.1", 0), server.ResultHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join()
        self.httpd.server_close()

    def post(self, payload):
        request = Request(
            f"http://127.0.0.1:{self.httpd.server_port}/results",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer token", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        return response.status, json.loads(response.read())

    def get(self):
        response = urlopen(f"http://127.0.0.1:{self.httpd.server_port}/results")
        return response.status, response.headers, json.loads(response.read())

    def test_serves_dashboard_at_root(self):
        response = urlopen(f"http://127.0.0.1:{self.httpd.server_port}/")

        self.assertEqual(200, response.status)
        self.assertEqual("text/html; charset=utf-8", response.headers["Content-Type"])
        self.assertIn(b"Judge results", response.read())

    def test_records_result(self):
        self.assertEqual((201, {"recorded": True}), self.post(result_payload()))
        self.save_result.assert_called_once()

    def test_rejects_invalid_status(self):
        payload = result_payload()
        payload["status"] = "SUCCESS"

        status, body = self.post(payload)
        self.assertEqual(400, status)
        self.assertIn("status", body["error"])

    def test_lists_results_for_dashboard(self):
        status, headers, body = self.get()

        self.assertEqual(200, status)
        self.assertEqual("*", headers["Access-Control-Allow-Origin"])
        self.assertEqual({"results": [{"status": "PASSED"}]}, body)


class AuthenticationTest(unittest.TestCase):
    environment = {
        "OIDC_AUDIENCE": "seminar-judge",
        "ALLOWED_SOURCE_REPOSITORY": "school/assignment",
        "ALLOWED_WORKFLOW_REF": WORKFLOW_REF,
    }

    @patch.dict("os.environ", environment, clear=True)
    @patch("server.verify_repository_source")
    @patch("server.decode_oidc_token")
    def test_matches_token_to_result(self, decode_oidc_token, verify_repository_source):
        decode_oidc_token.return_value = oidc_claims()
        server.authenticate_request("Bearer token", server.validate_request(result_payload()))
        verify_repository_source.assert_called_once_with("student/assignment")

    @patch.dict("os.environ", environment, clear=True)
    @patch("server.verify_repository_source")
    @patch("server.decode_oidc_token")
    def test_rejects_a_different_workflow(self, decode_oidc_token, _verify_repository_source):
        claims = oidc_claims()
        claims["job_workflow_ref"] = "attacker/judge/.github/workflows/grade.yml@refs/heads/main"
        decode_oidc_token.return_value = claims

        with self.assertRaises(PermissionError):
            server.authenticate_request("Bearer token", server.validate_request(result_payload()))

    def test_rejects_an_unknown_assignment(self):
        payload = result_payload()
        payload["assignment"] = "unknown"

        with self.assertRaises(ValueError):
            server.validate_request(payload)

    def test_verifies_token_signature_and_required_claims(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        claims = oidc_claims() | {
            "aud": "seminar-judge",
            "exp": now + 60,
            "iat": now,
            "iss": server.OIDC_ISSUER,
        }
        token = jwt.encode(claims, private_key, algorithm="RS256")

        with patch.object(
            server.OIDC_JWKS,
            "get_signing_key_from_jwt",
            return_value=SimpleNamespace(key=private_key.public_key()),
        ):
            decoded = server.decode_oidc_token(token, "seminar-judge")

        self.assertEqual(WORKFLOW_REF, decoded["job_workflow_ref"])


class RepositoryVerificationTest(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {"ALLOWED_SOURCE_REPOSITORY": "school/assignment"},
        clear=True,
    )
    @patch("server.urlopen")
    def test_accepts_a_fork_from_the_allowed_source(self, open_url):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "fork": True,
                "source": {"full_name": "school/assignment"},
            }
        ).encode()
        open_url.return_value = response

        server.verify_repository_source("student/assignment")

        request = open_url.call_args.args[0]
        self.assertEqual("https://api.github.com/repos/student/assignment", request.full_url)

    @patch.dict(
        "os.environ",
        {"ALLOWED_SOURCE_REPOSITORY": "school/assignment"},
        clear=True,
    )
    @patch("server.urlopen")
    def test_rejects_an_unrelated_repository(self, open_url):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"fork":false}'
        open_url.return_value = response

        with self.assertRaises(PermissionError):
            server.verify_repository_source("student/assignment")


class StorageTest(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {"SUPABASE_URL": "https://project.supabase.co", "SUPABASE_SECRET_KEY": "secret"},
        clear=True,
    )
    @patch("server.urlopen")
    def test_upserts_result_with_secret_key(self, open_url):
        response = MagicMock()
        response.__enter__.return_value.status = 201
        open_url.return_value = response

        server.save_result(server.validate_request(result_payload()))

        request = open_url.call_args.args[0]
        self.assertEqual("secret", request.get_header("Apikey"))
        self.assertIn("on_conflict=repository,assignment", request.full_url)
        self.assertEqual("resolution=merge-duplicates,return=minimal", request.get_header("Prefer"))
        row = json.loads(request.data)
        self.assertEqual(123, row["workflow_run_id"])
        self.assertIn("+00:00", row["graded_at"])

    @patch.dict(
        "os.environ",
        {"SUPABASE_URL": "https://project.supabase.co", "SUPABASE_SECRET_KEY": "secret"},
        clear=True,
    )
    @patch("server.urlopen")
    def test_loads_latest_results_with_secret_key(self, open_url):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = b'[{"status":"PASSED"}]'
        open_url.return_value = response

        self.assertEqual([{"status": "PASSED"}], server.load_results())

        request = open_url.call_args.args[0]
        self.assertEqual("secret", request.get_header("Apikey"))
        self.assertIn("order=graded_at.desc", request.full_url)
        self.assertIn("limit=100", request.full_url)


if __name__ == "__main__":
    unittest.main()
