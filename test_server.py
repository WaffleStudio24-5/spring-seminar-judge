import json
import threading
import time
import unittest
from http.server import HTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.authentication = patch("server.authenticate_request").start()
        self.addCleanup(patch.stopall)
        self.httpd = HTTPServer(("127.0.0.1", 0), server.GradingHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join()
        self.httpd.server_close()

    def post(self, payload):
        request = Request(
            f"http://127.0.0.1:{self.httpd.server_port}/gradings",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer token", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        return response.status, json.loads(response.read())

    @patch("server.run_grading", return_value=0)
    def test_returns_passed(self, run_grading):
        payload = {
            "repository": "https://github.com/user/assignment.git",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "assignment": "assignment-1-v1",
        }

        self.assertEqual((200, {"status": "PASSED"}), self.post(payload))
        run_grading.assert_called_once()

    @patch("server.run_grading", return_value=128)
    def test_distinguishes_runner_error(self, _run_grading):
        payload = {
            "repository": "https://github.com/user/assignment.git",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "assignment": "assignment-1-v1",
        }

        status, body = self.post(payload)
        self.assertEqual(500, status)
        self.assertEqual("ERROR", body["status"])

    @patch("server.run_grading", return_value=1)
    def test_returns_failed(self, _run_grading):
        payload = {
            "repository": "https://github.com/user/assignment.git",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "assignment": "assignment-1-v1",
        }

        self.assertEqual((200, {"status": "FAILED"}), self.post(payload))

    def test_rejects_invalid_repository(self):
        payload = {
            "repository": "file:///etc/passwd",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "assignment": "assignment-1-v1",
        }

        status, body = self.post(payload)
        self.assertEqual(400, status)
        self.assertIn("repository", body["error"])


class AuthenticationTest(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "OIDC_AUDIENCE": "seminar-judge",
            "ALLOWED_REPOSITORY_OWNER": "wafflestudio",
            "ALLOWED_ASSIGNMENTS": "assignment-1-v1",
        },
        clear=True,
    )
    @patch("server.decode_oidc_token")
    def test_matches_token_to_request(self, decode_oidc_token):
        commit = "0123456789abcdef0123456789abcdef01234567"
        decode_oidc_token.return_value = {
            "repository": "wafflestudio/assignment",
            "repository_owner": "wafflestudio",
            "sha": commit,
            "ref": "refs/heads/main",
        }

        server.authenticate_request(
            "Bearer token",
            "https://github.com/wafflestudio/assignment.git",
            commit,
            "assignment-1-v1",
        )

    @patch.dict(
        "os.environ",
        {
            "OIDC_AUDIENCE": "seminar-judge",
            "ALLOWED_REPOSITORY_OWNER": "wafflestudio",
            "ALLOWED_ASSIGNMENTS": "assignment-1-v1",
        },
        clear=True,
    )
    @patch("server.decode_oidc_token")
    def test_rejects_a_different_commit(self, decode_oidc_token):
        decode_oidc_token.return_value = {
            "repository": "wafflestudio/assignment",
            "repository_owner": "wafflestudio",
            "sha": "f" * 40,
            "ref": "refs/heads/main",
        }

        with self.assertRaises(PermissionError):
            server.authenticate_request(
                "Bearer token",
                "https://github.com/wafflestudio/assignment.git",
                "0" * 40,
                "assignment-1-v1",
            )

    def test_verifies_token_signature_and_standard_claims(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        token = jwt.encode(
            {
                "aud": "seminar-judge",
                "exp": now + 60,
                "iat": now,
                "iss": server.OIDC_ISSUER,
                "repository": "wafflestudio/assignment",
                "repository_owner": "wafflestudio",
                "ref": "refs/heads/main",
                "sha": "0" * 40,
            },
            private_key,
            algorithm="RS256",
        )

        with patch.object(
            server.OIDC_JWKS,
            "get_signing_key_from_jwt",
            return_value=SimpleNamespace(key=private_key.public_key()),
        ):
            claims = server.decode_oidc_token(token, "seminar-judge")

        self.assertEqual("wafflestudio/assignment", claims["repository"])


if __name__ == "__main__":
    unittest.main()
