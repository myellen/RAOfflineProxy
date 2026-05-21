import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from linux.raofflineproxy import auth
from linux.raofflineproxy import cache_keys
from linux.raofflineproxy import platform
from linux.raofflineproxy import retroarch_cfg
from linux.raofflineproxy import storage


class LinuxAuthTests(unittest.TestCase):
    def test_password_credentials_are_not_returned_as_token_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "retroarch.cfg"
            cfg_path.write_text(
                'cheevos_username = "misantronic"\ncheevos_password = "secret"\n',
                encoding="utf-8",
            )

            self.assertIsNone(
                retroarch_cfg.load_retroarch_token_credentials(str(cfg_path))
            )
            self.assertEqual(
                retroarch_cfg.load_retroarch_password_credentials(str(cfg_path)),
                {"user": "misantronic", "password": "secret"},
            )

    def test_resolve_credentials_logs_in_and_caches_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            cfg_path = root / "retroarch.cfg"
            cfg_path.write_text(
                'cheevos_username = "misantronic"\ncheevos_password = "secret"\n',
                encoding="utf-8",
            )
            store = storage.Storage(database_path=db_path)
            original_http_get = auth.http_get
            try:
                captured = {}

                def fake_http_get(url: str, _user_agent: str) -> str:
                    captured["url"] = url
                    return '{"Success":true,"User":"misantronic","Token":"token"}'

                auth.http_get = fake_http_get

                credentials = auth.resolve_credentials(
                    store,
                    {"retroarch_cfg": str(cfg_path)},
                    "RetroArch/1.20.0",
                )

                self.assertEqual(credentials, {"user": "misantronic", "token": "token"})
                self.assertIn("r=login2", captured["url"])
                self.assertIsNotNone(store.get_cache(cache_keys.login("misantronic")))
            finally:
                auth.http_get = original_http_get
                store.close()

    def test_resolve_credentials_uses_token_before_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            cfg_path = root / "retroarch.cfg"
            cfg_path.write_text(
                'cheevos_username = "misantronic"\n'
                'cheevos_token = "cfg-token"\n'
                'cheevos_password = "secret"\n',
                encoding="utf-8",
            )
            store = storage.Storage(database_path=db_path)
            original_http_get = auth.http_get
            try:

                def fake_http_get(_url: str, _user_agent: str) -> str:
                    raise AssertionError(
                        "login2 should not be called when token exists"
                    )

                auth.http_get = fake_http_get

                credentials = auth.resolve_credentials(
                    store,
                    {"retroarch_cfg": str(cfg_path)},
                    "RetroArch/1.20.0",
                )

                self.assertEqual(
                    credentials,
                    {"user": "misantronic", "token": "cfg-token"},
                )
                self.assertIsNotNone(store.get_cache(cache_keys.login("misantronic")))
            finally:
                auth.http_get = original_http_get
                store.close()

    def test_resolve_credentials_uses_cfg_token_before_cached_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            cfg_path = root / "retroarch.cfg"
            cfg_path.write_text(
                'cheevos_username = "misantronic"\ncheevos_token = "cfg-token"\n',
                encoding="utf-8",
            )
            store = storage.Storage(database_path=db_path)
            try:
                store.upsert_cache(
                    cache_keys.login("misantronic"),
                    '{"Success":true,"User":"misantronic","Token":"old-token"}',
                )

                credentials = auth.resolve_credentials(
                    store,
                    {"retroarch_cfg": str(cfg_path)},
                    "RetroArch/1.20.0",
                )

                self.assertEqual(
                    credentials,
                    {"user": "misantronic", "token": "cfg-token"},
                )
            finally:
                store.close()


    def test_muos_cheevos_cfg_is_a_credential_candidate(self) -> None:
        # muOS stores the RA login in a sibling retroarch.cheevos.cfg (it blanks
        # cheevos_* in the global cfg), so that file must be a credential
        # candidate -- but AFTER the global cfg, which stays the patch target.
        from linux.raofflineproxy import config

        listed = [str(p) for p in config._retroarch_cfg_candidate_list()]
        self.assertIn(
            "/opt/muos/share/info/config/retroarch.cheevos.cfg", listed
        )
        self.assertLess(
            listed.index("/opt/muos/share/info/config/retroarch.cfg"),
            listed.index("/opt/muos/share/info/config/retroarch.cheevos.cfg"),
        )

    def test_credentials_any_searches_every_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            no_creds = root / "primary.cfg"
            no_creds.write_text('cheevos_enable = "true"\n', encoding="utf-8")
            has_creds = root / "secondary.cfg"
            has_creds.write_text(
                'cheevos_username = "misantronic"\ncheevos_token = "tok"\n',
                encoding="utf-8",
            )
            self.assertIsNone(
                retroarch_cfg.load_retroarch_credentials_any([str(no_creds)])
            )
            self.assertEqual(
                retroarch_cfg.load_retroarch_credentials_any(
                    [str(no_creds), str(has_creds)]
                ),
                {"user": "misantronic", "token": "tok"},
            )

    def test_search_list_is_primary_first_and_deduped(self) -> None:
        with mock.patch(
            "linux.raofflineproxy.platform.retroarch_cfg_candidates",
            return_value=["/a/primary.cfg", "/b/other.cfg"],
        ):
            result = platform.resolve_retroarch_cfg_search(
                {"retroarch_cfg": "/a/primary.cfg"}
            )
        self.assertEqual(result, ["/a/primary.cfg", "/b/other.cfg"])

    def test_resolve_credentials_falls_back_to_other_cfg_for_token(self) -> None:
        # muOS case: Start patched the primary cfg, but RetroArch saved the login
        # token to a different file. The token must still be found there.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = root / "primary.cfg"
            primary.write_text(
                'cheevos_custom_host = "127.0.0.1:8080"\n', encoding="utf-8"
            )
            other = root / "login.cfg"
            other.write_text(
                'cheevos_username = "misantronic"\ncheevos_token = "real-token"\n',
                encoding="utf-8",
            )
            store = storage.Storage(database_path=root / "t.sqlite3")
            try:
                with mock.patch(
                    "linux.raofflineproxy.platform.retroarch_cfg_candidates",
                    return_value=[str(other)],
                ):
                    creds = auth.resolve_credentials(
                        store, {"retroarch_cfg": str(primary)}, "RetroArch/1.20.0"
                    )
                self.assertEqual(creds, {"user": "misantronic", "token": "real-token"})
                self.assertIsNotNone(store.get_cache(cache_keys.login("misantronic")))
            finally:
                store.close()

    def test_resolve_credentials_prefers_primary_cfg_token(self) -> None:
        # Regression guard: when the primary cfg has the token, the fallback list
        # must not change the result (other platforms keep working unchanged).
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = root / "primary.cfg"
            primary.write_text(
                'cheevos_username = "misantronic"\ncheevos_token = "primary-token"\n',
                encoding="utf-8",
            )
            other = root / "other.cfg"
            other.write_text(
                'cheevos_username = "someoneelse"\ncheevos_token = "other-token"\n',
                encoding="utf-8",
            )
            store = storage.Storage(database_path=root / "t.sqlite3")
            try:
                with mock.patch(
                    "linux.raofflineproxy.platform.retroarch_cfg_candidates",
                    return_value=[str(other)],
                ):
                    creds = auth.resolve_credentials(
                        store, {"retroarch_cfg": str(primary)}, "RetroArch/1.20.0"
                    )
                self.assertEqual(
                    creds, {"user": "misantronic", "token": "primary-token"}
                )
            finally:
                store.close()


    def test_import_saved_login_seeds_login_cache_from_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cfg = root / "retroarch.cfg"
            cfg.write_text(
                'cheevos_username = "tester"\ncheevos_token = "TOK"\n', encoding="utf-8"
            )
            store = storage.Storage(database_path=root / "t.sqlite3")
            try:
                self.assertIsNone(store.get_cache(cache_keys.login("tester")))
                result = auth.import_saved_login(store, {"retroarch_cfg": str(cfg)})
                self.assertEqual(result, {"user": "tester", "token": "TOK"})
                cached = store.get_cache(cache_keys.login("tester"))
                self.assertIsNotNone(cached)
                payload = json.loads(cached["responseBody"])
                self.assertTrue(payload["Success"])
                self.assertEqual(payload["Token"], "TOK")
            finally:
                store.close()

    def test_import_saved_login_keeps_richer_existing_login(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cfg = root / "retroarch.cfg"
            cfg.write_text(
                'cheevos_username = "tester"\ncheevos_token = "TOK"\n', encoding="utf-8"
            )
            store = storage.Storage(database_path=root / "t.sqlite3")
            try:
                store.upsert_cache(
                    cache_keys.login("tester"),
                    '{"Success":true,"User":"tester","Token":"TOK","Score":999}',
                )
                auth.import_saved_login(store, {"retroarch_cfg": str(cfg)})
                payload = json.loads(
                    store.get_cache(cache_keys.login("tester"))["responseBody"]
                )
                self.assertEqual(payload["Score"], 999)  # not clobbered
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
