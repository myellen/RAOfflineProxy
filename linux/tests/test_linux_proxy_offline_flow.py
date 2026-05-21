import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from linux.raofflineproxy import auth, cache_keys, flusher, proxy_service, storage


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class LinuxProxyOfflineFlowTests(unittest.TestCase):
    def test_offline_unlock_is_served_queued_reflected_and_flushed(self) -> None:
        game_hash, gid, user, ach = "abc123def456", 42, "tester", 111

        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "retroarch.cfg"
            cfg_path.write_text('cheevos_username = "tester"\ncheevos_token = "TOK"\n')
            store = storage.Storage(database_path=Path(tmp) / "proxy.sqlite3")
            try:
                store.upsert_cache(cache_keys.game_id(game_hash),
                                   json.dumps({"Success": True, "GameID": gid}))
                store.upsert_cache(cache_keys.patch(gid, user), json.dumps(
                    {"Success": True, "PatchData": {"ID": gid, "Title": "Test Game",
                     "Achievements": [{"ID": ach, "Title": "First Steps", "Points": 5, "Flags": 3}]}}))
                store.upsert_cache(cache_keys.start_session(gid, user), json.dumps(
                    {"Success": True, "Unlocks": [], "HardcoreUnlocks": [],
                     "ServerNow": int(time.time())}))
                auth.import_saved_login(store, {"retroarch_cfg": str(cfg_path)})

                server = proxy_service.ProxyRuntimeServer(
                    {"proxy_host": "127.0.0.1", "proxy_port": _free_port(),
                     "upstream_host": "http://127.0.0.1:1"}, store)
                server.is_online = lambda: False
                port = server.server_address[1]
                serving = threading.Thread(
                    target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
                serving.start()
                try:
                    self._run_offline_phase(port, game_hash, gid, user, ach, store)
                finally:
                    server.shutdown()
                    serving.join(5)
                    server.server_close()

                self._run_flush_phase(store, cfg_path, ach)
            finally:
                store.close()

    def test_run_proxy_service_imports_login_when_online(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "retroarch.cfg"
            cfg.write_text('cheevos_username = "tester"\ncheevos_password = "pw"\n')
            store = storage.Storage(database_path=Path(tmp) / "proxy.sqlite3")
            stop = threading.Event()
            stop.set()
            calls: list = []
            with mock.patch.object(proxy_service, "Storage", lambda: store), \
                mock.patch.object(
                    proxy_service.ProxyRuntimeServer, "refresh_reachability",
                    lambda self, force_probe=False: True), \
                mock.patch.object(
                    proxy_service, "resolve_credentials",
                    lambda s, c: calls.append((s, c))):
                proxy_service.run_proxy_service(
                    {"proxy_host": "127.0.0.1", "proxy_port": _free_port(),
                     "retroarch_cfg": str(cfg)},
                    stop,
                )
            self.assertEqual(len(calls), 1)

    def _call(self, port: int, params: str, body: str | None = None) -> dict:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/dorequest.php?{params}",
            data=body.encode() if body else None,
            headers={"User-Agent": "RetroArch/1.21.0 (Linux)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return json.loads(exc.read())

    def _run_offline_phase(self, port, game_hash, gid, user, ach, store) -> None:
        login = self._call(port, f"r=login2&u={user}&t=TOK")
        self.assertTrue(login.get("Success"))
        self.assertEqual(login.get("Token"), "TOK")
        self.assertEqual(self._call(port, f"r=gameid&m={game_hash}").get("GameID"), gid)
        self.assertTrue(self._call(port, f"r=patch&g={gid}&u={user}&t=TOK").get("PatchData"))
        self.assertTrue(self._call(port, f"r=startsession&g={gid}&u={user}&t=TOK&h=0").get("Success"))

        award_q = f"r=awardachievement&a={ach}&u={user}&t=TOK&h=0&v=deadbeef"
        award = self._call(port, award_q, body=award_q)
        self.assertEqual(award.get("Error"), "queued_offline")
        self.assertEqual(len(store.get_pending_awards()), 1)

        again = self._call(port, f"r=startsession&g={gid}&u={user}&t=TOK&h=0")
        self.assertIn(ach, [u.get("ID") for u in again.get("Unlocks", [])])

    def _run_flush_phase(self, store, cfg_path: Path, ach: int) -> None:
        received: list[str] = []

        class Mock(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length).decode() if length else ""
                received.append(self.path + ("?" + body if body else ""))
                payload = json.dumps({"Success": True, "Token": "TOK", "Score": 5,
                                      "AchievementID": ach}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _handle
            do_POST = _handle

        mock = HTTPServer(("127.0.0.1", 0), Mock)
        mock_port = mock.server_address[1]
        mock_thread = threading.Thread(target=mock.serve_forever, daemon=True)
        mock_thread.start()
        try:
            flusher.flush_pending_awards(
                store,
                {"upstream_host": f"http://127.0.0.1:{mock_port}",
                 "retroarch_cfg": str(cfg_path)},
            )
        finally:
            mock.shutdown()
            mock_thread.join(5)
            mock.server_close()

        self.assertTrue(
            any("awardachievement" in r and f"a={ach}" in r for r in received),
            f"upstream did not receive the award replay: {received}",
        )
        self.assertEqual(len(store.get_pending_awards()), 0)


if __name__ == "__main__":
    unittest.main()
