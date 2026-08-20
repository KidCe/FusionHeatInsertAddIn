import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import hardware_library_editor_server as editor_server


ROOT = Path(__file__).resolve().parents[1]


class EditorServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.library_path = Path(self.temp_directory.name) / "hardware_library.json"
        shutil.copyfile(ROOT / "hardware_library.json", self.library_path)
        self.original_library_path = editor_server.LIBRARY_PATH
        editor_server.LIBRARY_PATH = self.library_path
        self.server = editor_server.ThreadingHTTPServer(
            ("127.0.0.1", 0), editor_server.EditorHandler
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        editor_server.LIBRARY_PATH = self.original_library_path
        self.temp_directory.cleanup()

    def test_library_can_be_loaded_and_saved(self):
        with urllib.request.urlopen(self.base_url + "/hardware_library.json") as response:
            library = json.load(response)
        library["insertProfiles"][0]["notes"] = "Editor server test"
        request = urllib.request.Request(
            self.base_url + "/hardware_library.json",
            data=(json.dumps(library) + "\n").encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(request) as response:
            self.assertTrue(json.load(response)["saved"])
        saved = json.loads(self.library_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["insertProfiles"][0]["notes"], "Editor server test")

    def test_server_does_not_expose_arbitrary_files(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(self.base_url + "/FusionHeatInsertAddIn.py")
        self.assertEqual(context.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
