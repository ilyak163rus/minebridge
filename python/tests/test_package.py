"""Check resources and typing metadata from an installed distribution."""

import base64
import hashlib
from importlib import metadata, resources
import json
from pathlib import Path
import unittest

import minebridge
from minebridge import block, effects, entity, items, selector
from minebridge.models import normalize_block


class InstalledPackageTests(unittest.TestCase):
    def _installed_distribution(self):
        source = Path(__file__).resolve().parents[1] / "src" / "minebridge"
        if Path(minebridge.__file__).resolve().parent == source:
            self.skipTest("Installed-wheel metadata is checked by the I05 clean-venv run")
        distribution = metadata.distribution("minebridge")
        self.assertEqual(Path(distribution.locate_file("minebridge/__init__.py")).resolve(),
                         Path(minebridge.__file__).resolve())
        return distribution

    def test_installed_distribution_contains_typing_marker(self) -> None:
        self.assertTrue(resources.files("minebridge").joinpath("py.typed").is_file())
        # I02-I04 run directly from source, by the user's request to defer wheel
        # builds. Installed-distribution RECORD is checked again on final I05.
        source = Path(__file__).resolve().parents[1] / "src" / "minebridge"
        if Path(minebridge.__file__).resolve().parent == source:
            return
        paths = {str(path).replace("\\", "/") for path in metadata.files("minebridge") or ()}
        self.assertIn("minebridge/py.typed", paths)

    def test_packaged_table_is_complete_and_used_by_normalization(self) -> None:
        resource = resources.files("minebridge._data").joinpath("legacy-blocks-v0.2.json")
        document = json.loads(resource.read_text(encoding="utf-8"))
        self.assertEqual(document["formatVersion"], 1)
        rows = document["blocks"]
        pairs = {(row["id"], row["data"]) for row in rows}
        self.assertEqual(len(pairs), len(rows))
        self.assertEqual(len(rows), 361)
        self.assertTrue({(0, 0), (1, 0), (4, 0)}.issubset(pairs))
        for row in rows:
            value = normalize_block(row["id"], row["data"])
            self.assertEqual((value.key, dict(value.states)), (row["key"], row.get("states", {})))

    def test_all_registry_resources_and_typed_catalogs_are_packaged(self) -> None:
        data = resources.files("minebridge._data")
        blocks = json.loads(data.joinpath("blocks-paper-26.2.json").read_text(encoding="utf-8"))
        game = json.loads(data.joinpath("game-paper-26.2.json").read_text(encoding="utf-8"))
        self.assertEqual((blocks["minecraftVersion"], blocks["paperBuild"]), ("26.2", 133))
        self.assertEqual((game["minecraftVersion"], game["paperBuild"]), ("26.2", 133))
        self.assertEqual(len(blocks["blocks"]), 1196)
        self.assertEqual({normalize_block(getattr(block, name)).key for name in block.__all__},
                         {row["key"] for row in blocks["blocks"]})
        for collection, module, count in (("items", items, 1537), ("effects", effects, 40),
                                           ("entities", entity, 158)):
            self.assertEqual(len(game[collection]), count)
            self.assertEqual({getattr(module, name).key for name in module.__all__},
                             {row["key"] for row in game[collection]})

    def test_package_metadata_has_no_runtime_dependencies(self) -> None:
        distribution = self._installed_distribution()
        self.assertEqual(distribution.version, minebridge.__version__)
        self.assertIsNone(distribution.metadata.get("Requires-Dist"))
        self.assertEqual(distribution.metadata["Requires-Python"], ">=3.11")

    def test_installed_record_matches_package_bytes(self) -> None:
        distribution = self._installed_distribution()
        paths = {str(path).replace("\\", "/"): path for path in distribution.files or ()}
        expected = {"minebridge/py.typed", "minebridge/block.py", "minebridge/items.py",
                    "minebridge/effects.py", "minebridge/entity.py", "minebridge/selector.py",
                    "minebridge/_data/legacy-blocks-v0.2.json",
                    "minebridge/_data/blocks-paper-26.2.json", "minebridge/_data/game-paper-26.2.json"}
        self.assertTrue(expected.issubset(paths))
        for name, entry in paths.items():
            if not name.startswith("minebridge/") or name.endswith(".pyc"):
                continue
            with self.subTest(file=name):
                content = Path(distribution.locate_file(entry)).read_bytes()
                self.assertIsNotNone(entry.hash)
                self.assertEqual(entry.size, len(content))
                digest = hashlib.new(entry.hash.mode, content).digest()
                self.assertEqual(entry.hash.value, base64.urlsafe_b64encode(digest).rstrip(b"=").decode())

    def test_static_constants_are_publicly_discoverable(self) -> None:
        self.assertTrue({"AIR", "STONE", "COBBLESTONE"}.issubset(dir(block)))
        self.assertTrue({"AIR", "STONE", "COBBLESTONE"}.issubset(block.__all__))
        self.assertTrue({"SELF", "ALL_PLAYERS", "ALL_ENTITIES"}.issubset(selector.__all__))


if __name__ == "__main__":
    unittest.main()
