#!/usr/bin/env python3
"""Run only on local Linux/WSL; all deployment paths and services are isolated."""
from functools import partial
import grp
import http.server
import io
import os
from pathlib import Path
import pwd
import subprocess
import tarfile
import tempfile
import threading
import unittest


SCRIPT = Path(__file__).resolve().with_name("deploy-frontend-atomic.sh")
INDEX = '<html><script src="/assets/main-new.js"></script><link rel="stylesheet" href="/assets/main-new.css"></html>'
FILES = {
    "index.html": INDEX,
    "assets/main-new.js": 'import("./lazy-new.js");const deps=["assets/main-new.css"];',
    "assets/lazy-new.js": 'export const value="new";',
    "assets/main-new.css": "body{color:blue}",
}


class FrontendDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tokenpool-deploy-test-")
        self.root = Path(self.temp.name)
        self.releases = self.root / "releases"
        self.old = self.releases / "old"
        (self.old / "assets").mkdir(parents=True)
        (self.old / "index.html").write_text("<html>old homepage</html>")
        (self.old / "assets/old-hash.js").write_text("old cached chunk")
        self.current = self.root / "current"
        self.current.symlink_to(self.old)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.write_stub("nginx", '#!/bin/sh\n[ "${TEST_NGINX_FAIL:-0}" != 1 ]\n')
        self.write_stub("systemctl", '''#!/bin/sh
echo "$*" >> "$TEST_SERVICE_LOG"
if [ "${TEST_RELOAD_FAIL_ONCE:-0}" = 1 ] && [ ! -f "$TEST_RELOAD_STATE" ]; then
  touch "$TEST_RELOAD_STATE"
  exit 1
fi
''')
        self.bad_asset = False
        owner = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if owner.bad_asset and self.path == "/assets/main-new.js":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"wrong asset despite HTTP 200")
                else:
                    super().do_GET()

        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(Handler, directory=str(self.current))
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + ":" + os.environ["PATH"],
            "TOKENPOOL_RELEASE_ROOT": str(self.releases),
            "TOKENPOOL_CURRENT_LINK": str(self.current),
            "TOKENPOOL_WEB_OWNER": pwd.getpwuid(os.getuid()).pw_name,
            "TOKENPOOL_WEB_GROUP": grp.getgrgid(os.getgid()).gr_name,
            "TOKENPOOL_HTTP_BASE_URL": f"http://127.0.0.1:{self.server.server_port}",
            "TEST_SERVICE_LOG": str(self.root / "service.log"),
            "TEST_RELOAD_STATE": str(self.root / "reload.failed"),
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def write_stub(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def archive(self, files=None, extra=None):
        result = self.root / "dist.tar.gz"
        with tarfile.open(result, "w:gz") as bundle:
            for name, text in (FILES if files is None else files).items():
                data = text.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
            if extra:
                bundle.addfile(extra, io.BytesIO(b"x") if extra.isfile() else None)
        return result

    def deploy(self, archive=None, **environment):
        return subprocess.run(
            ["bash", str(SCRIPT), str(archive or self.archive()), "new"],
            env={**self.env, **environment}, capture_output=True, text=True, timeout=30,
        )

    def assert_old_active(self):
        self.assertEqual(self.current.resolve(), self.old)
        self.assertTrue((self.old / "assets/old-hash.js").is_file())

    def test_success_preserves_previous_assets_and_release(self):
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.current.resolve(), self.releases / "new")
        self.assertEqual((self.current / "assets/old-hash.js").read_text(), "old cached chunk")
        self.assertTrue((self.old / "index.html").exists())
        self.assertIn("HTTP verification passed", result.stdout)

    def test_nginx_invalid_never_activates_or_extracts(self):
        result = self.deploy(TEST_NGINX_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_active()
        self.assertFalse((self.releases / "new").exists())

    def test_missing_static_dependency_never_activates(self):
        files = {**FILES, "index.html": '<script src="/assets/missing.js"></script>'}
        result = self.deploy(self.archive(files))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing/unsafe local reference", result.stderr)
        self.assert_old_active()

    def test_missing_dynamic_dependency_never_activates(self):
        files = {**FILES, "assets/main-new.js": 'import("./missing.js")'}
        result = self.deploy(self.archive(files))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing/unsafe local reference", result.stderr)
        self.assert_old_active()

    def test_http_mismatch_rolls_back_even_when_status_is_200(self):
        self.bad_asset = True
        result = self.deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP content mismatch", result.stderr)
        self.assert_old_active()
        self.assertTrue((self.releases / "new/index.html").exists())
        self.assertEqual((self.root / "service.log").read_text().count("reload nginx"), 2)

    def test_reload_failure_rolls_back(self):
        result = self.deploy(TEST_RELOAD_FAIL_ONCE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_active()
        self.assertEqual((self.root / "service.log").read_text().count("reload nginx"), 2)

    def test_asset_collision_rejected(self):
        (self.old / "assets/main-new.js").write_text("same name, other bytes")
        result = self.deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Asset name collision", result.stderr)
        self.assert_old_active()

    def test_unsafe_archive_members_are_rejected_before_extraction(self):
        for name, kind in [("../escaped", tarfile.REGTYPE),
                           ("/tmp/escaped", tarfile.REGTYPE),
                           ("assets/symlink", tarfile.SYMTYPE),
                           ("assets/hardlink", tarfile.LNKTYPE)]:
            with self.subTest(name=name):
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = 1 if kind == tarfile.REGTYPE else 0
                info.linkname = "/tmp/escaped"
                result = self.deploy(self.archive(extra=info))
                self.assertNotEqual(result.returncode, 0)
                self.assert_old_active()
                self.assertFalse((self.releases / "new").exists())
                self.assertFalse((self.root / "escaped").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
