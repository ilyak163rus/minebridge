"""Check resources and typing metadata from an installed distribution."""

from importlib import metadata, resources
import json
import unittest

import minebridge
from minebridge import block
from minebridge.models import normalize_block


class InstalledPackageTests(unittest.TestCase):
    def test_installed_distribution_contains_typing_marker(self) -> None:
        paths = {str(path).replace("\\", "/") for path in metadata.files("minebridge") or ()}
        self.assertIn("minebridge/py.typed", paths)
        self.assertTrue(resources.files("minebridge").joinpath("py.typed").is_file())

    def test_packaged_table_is_complete_and_used_by_normalization(self) -> None:
        resource = resources.files("minebridge._data").joinpath("legacy-blocks-v0.1.json")
        document = json.loads(resource.read_text(encoding="utf-8"))
        self.assertEqual(document["formatVersion"], 1)
        rows = document["blocks"]
        self.assertEqual({(row["id"], row["data"]) for row in rows}, {(0, 0), (1, 0), (4, 0)})
        self.assertEqual(len(rows), 3)
        self.assertTrue(document["source"]["url"].startswith("https://github.com/"))
        for row in rows:
            self.assertEqual(normalize_block(row["id"], row["data"]).key, row["key"])

    def test_package_metadata_has_no_runtime_dependencies(self) -> None:
        self.assertEqual(metadata.version("minebridge"), minebridge.__version__)
        self.assertIsNone(metadata.metadata("minebridge").get("Requires-Dist"))
        self.assertEqual(metadata.metadata("minebridge")["Requires-Python"], ">=3.11")

    def test_static_constants_are_publicly_discoverable(self) -> None:
        self.assertTrue({"AIR", "STONE", "COBBLESTONE"}.issubset(dir(block)))
        self.assertEqual(set(block.__all__), {"AIR", "STONE", "COBBLESTONE"})


if __name__ == "__main__":
    unittest.main()
