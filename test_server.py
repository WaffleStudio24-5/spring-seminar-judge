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
WORKFLOW_SHA = "a" * 40
WORKFLOW_REF = (
    "WaffleStudio24-5/spring-seminar-judge/.github/workflows/grade.yml@refs/heads/main"
)


def result_payload():
    return {
        "repository": "student/assignment",
        "commit": COMMIT,
        "assignment": "assignment-1-v1",
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
        "job_workflow_sha": WORKFLOW_SHA,
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
        "ALLOWED_REPOSITORIES": "student/assignment",
        "ALLOWED_ASSIGNMENTS": f"assignment-1-v1={COMMIT}",
        "ALLOWED_WORKFLOW_REF": WORKFLOW_REF,
        "ALLOWED_WORKFLOW_SHAS": WORKFLOW_SHA,
    }

    @patch.dict("os.environ", environment, clear=True)
    @patch("server.decode_oidc_token")
    def test_matches_token_to_result(self, decode_oidc_token):
        decode_oidc_token.return_value = oidc_claims()
        server.authenticate_request("Bearer token", server.validate_request(result_payload()))

    @patch.dict("os.environ", environment, clear=True)
    @patch("server.decode_oidc_token")
    def test_rejects_a_different_workflow_commit(self, decode_oidc_token):
        claims = oidc_claims()
        claims["job_workflow_sha"] = "f" * 40
        decode_oidc_token.return_value = claims

        with self.assertRaises(PermissionError):
            server.authenticate_request("Bearer token", server.validate_request(result_payload()))

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

        self.assertEqual(WORKFLOW_SHA, decoded["job_workflow_sha"])


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
        self.assertIn("on_conflict=repository,assignment,workflow_run_id,run_attempt", request.full_url)
        self.assertEqual(123, json.loads(request.data)["workflow_run_id"])

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
