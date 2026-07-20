"""Security-hardening fixes: auth timing-safety, fail-closed, no fingerprint leak."""

import importlib
import unittest
from unittest import mock

from fastapi import HTTPException


def _reload_api(env):
    with mock.patch.dict("os.environ", env, clear=False):
        import resolve_control_plane.api as api
        importlib.reload(api)
        return api


class _Req:
    def __init__(self, auth=None):
        self.headers = {"authorization": auth} if auth is not None else {}


class AuthTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        import resolve_control_plane.api as api
        importlib.reload(api)  # restore ambient env for other tests

    def test_correct_token_passes_bearer_and_bare(self):
        api = _reload_api({"CP_TOKEN": "secret123", "AUTH_DEBUG": "", "ALLOW_NO_AUTH": ""})
        api.auth(_Req("Bearer secret123"))   # no raise
        api.auth(_Req("secret123"))          # bare also accepted

    def test_bad_token_gives_generic_401_no_fingerprint(self):
        api = _reload_api({"CP_TOKEN": "secret123", "AUTH_DEBUG": ""})
        with self.assertRaises(HTTPException) as cm:
            api.auth(_Req("Bearer wrongwrong"))
        self.assertEqual(cm.exception.status_code, 401)
        # must NOT leak length or edge chars of what arrived
        self.assertEqual(cm.exception.detail, "bad token")
        self.assertNotIn("chars", str(cm.exception.detail))

    def test_debug_flag_opts_into_fingerprint(self):
        api = _reload_api({"CP_TOKEN": "secret123", "AUTH_DEBUG": "1"})
        with self.assertRaises(HTTPException) as cm:
            api.auth(_Req("Bearer wrong"))
        self.assertIn("chars", str(cm.exception.detail))

    def test_missing_token_fails_closed_503(self):
        api = _reload_api({"CP_TOKEN": "", "ALLOW_NO_AUTH": ""})
        with self.assertRaises(HTTPException) as cm:
            api.auth(_Req("anything"))
        self.assertEqual(cm.exception.status_code, 503)

    def test_allow_no_auth_opts_back_into_open(self):
        api = _reload_api({"CP_TOKEN": "", "ALLOW_NO_AUTH": "true"})
        api.auth(_Req())  # no raise — explicit local-dev opt-in

    def test_whitespace_mangled_token_still_accepted(self):
        api = _reload_api({"CP_TOKEN": "secret123"})
        api.auth(_Req("Bearer  secret123\n"))     # doubled space + newline
        api.auth(_Req("Bearer secret123"))   # non-breaking space


if __name__ == "__main__":
    unittest.main()
