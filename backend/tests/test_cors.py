import asyncio
import unittest

from app.main import app


class CorsTests(unittest.TestCase):
    def test_local_vite_origin_is_allowed(self) -> None:
        messages = []

        async def receive():
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "OPTIONS",
            "scheme": "http",
            "path": "/problems",
            "raw_path": b"/problems",
            "query_string": b"",
            "headers": [
                (b"origin", b"http://127.0.0.1:5173"),
                (b"access-control-request-method", b"GET"),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
        }

        asyncio.run(app(scope, receive, send))
        response_start = next(
            message
            for message in messages
            if message["type"] == "http.response.start"
        )
        headers = dict(response_start["headers"])

        self.assertEqual(response_start["status"], 200)
        self.assertEqual(
            headers[b"access-control-allow-origin"],
            b"http://127.0.0.1:5173",
        )


if __name__ == "__main__":
    unittest.main()
