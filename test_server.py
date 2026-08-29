import json
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


class ServerTest(unittest.TestCase):
    def setUp(self):
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
            headers={"Content-Type": "application/json"},
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


if __name__ == "__main__":
    unittest.main()
