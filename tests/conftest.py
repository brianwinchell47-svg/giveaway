import functools
import http.server
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from giveaway_bot.config import Config, Profile, Settings
from giveaway_bot.runner import launch_browser

FIX = Path(__file__).parent / "fixtures"


REQUESTS: list[str] = []  # every path the test server was asked for


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        REQUESTS.append(self.path)
        super().do_GET()

    def do_POST(self):
        REQUESTS.append("POST " + self.path)
        self.send_response(200)
        self.end_headers()


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(_Handler, directory=str(FIX))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def ctx():
    with sync_playwright() as pw:
        b = launch_browser(pw)
        yield b.new_context()
        b.close()


@pytest.fixture
def cfg(tmp_path):
    p = Profile(state="IL", state_name="Illinois", birthdate="1990-04-15")
    return Config(p, [], [], Settings(data_dir=str(tmp_path)))
