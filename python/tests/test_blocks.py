"""Contract tests for the offline T01 block API."""

from __future__ import annotations

import unittest

from minebridge import block
from minebridge.errors import (
    InvalidBlockError,
    MinecraftError,
    UnsupportedFeatureError,
    UnsupportedLegacyBlockError,
)
from minebridge.models.blocks import BlockSpec, LegacyBlock, normalize_block


SUPPORTED_BLOCKS = (
    (0, "AIR", "minecraft:air"),
    (1, "STONE", "minecraft:stone"),
    (4, "COBBLESTONE", "minecraft:cobblestone"),
)


class BlockNormalizationTests(unittest.TestCase):
    def test_all_supported_input_forms_produce_same_specification(self) -> None:
        for legacy_id, constant_name, key in SUPPORTED_BLOCKS:
            expected = BlockSpec(key)
            for value in (
                legacy_id,
                LegacyBlock(legacy_id),
                getattr(block, constant_name),
                key,
                BlockSpec(key, {}),
            ):
                with self.subTest(value=value):
                    actual = normalize_block(value)
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual.key, key)
                    self.assertEqual(dict(actual.states), {})

    def test_explicit_zero_data_is_allowed_for_every_input_form(self) -> None:
        for value in (4, LegacyBlock(4), block.COBBLESTONE,
                      "minecraft:cobblestone", BlockSpec("minecraft:cobblestone")):
            with self.subTest(value=value):
                self.assertEqual(normalize_block(value, data=0),
                                 BlockSpec("minecraft:cobblestone"))

    def test_constants_keep_legacy_attributes(self) -> None:
        for legacy_id, constant_name, _ in SUPPORTED_BLOCKS:
            with self.subTest(constant=constant_name):
                constant = getattr(block, constant_name)
                self.assertIsInstance(constant, LegacyBlock)
                self.assertEqual(constant.id, legacy_id)
                self.assertEqual(constant.data, 0)

    def test_unknown_pairs_are_rejected_instead_of_replaced_with_air(self) -> None:
        for legacy_id, data in ((2, 0), (999, 0), (-1, 0), (0, 1),
                                (1, 1), (4, 1), (4, -1), (4, 256)):
            for value, separate_data in ((legacy_id, data),
                                         (LegacyBlock(legacy_id, data), 0)):
                with self.subTest(value=value, data=separate_data):
                    with self.assertRaises(UnsupportedLegacyBlockError) as caught:
                        normalize_block(value, data=separate_data)
                    self.assertIsInstance(caught.exception, MinecraftError)
                    self.assertEqual(caught.exception.code, "UNSUPPORTED_LEGACY_BLOCK")
                    self.assertEqual(caught.exception.outcome, "not-applied")

    def test_enormous_legacy_numbers_still_raise_the_domain_error(self) -> None:
        enormous = 10 ** 10000
        for index, (value, data) in enumerate((
            (enormous, 0), (4, enormous), (LegacyBlock(enormous), 0),
        )):
            with self.subTest(case=index):
                with self.assertRaises(UnsupportedLegacyBlockError):
                    normalize_block(value, data)

    def test_separate_nonzero_data_cannot_override_embedded_or_modern_data(self) -> None:
        for value in (LegacyBlock(4), LegacyBlock(4, 1),
                      "minecraft:cobblestone", BlockSpec("minecraft:cobblestone")):
            for data in (-1, 1, 256):
                with self.subTest(value=value, data=data):
                    with self.assertRaises(ValueError):
                        normalize_block(value, data=data)

    def test_bool_and_unsupported_input_types_are_not_coerced(self) -> None:
        for value in (True, False, None, 4.0, b"minecraft:stone", [], {}, object()):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    normalize_block(value)  # type: ignore[arg-type]

    def test_data_must_be_integer_and_not_bool_for_every_input_form(self) -> None:
        for value in (4, LegacyBlock(4), "minecraft:stone", BlockSpec("minecraft:stone")):
            for data in (True, False, 0.0, "0", None, [], {}):
                with self.subTest(value=value, data=data):
                    with self.assertRaises(TypeError):
                        normalize_block(value, data=data)  # type: ignore[arg-type]

    def test_invalid_keys_are_rejected_by_constructor_and_normalizer(self) -> None:
        for key in ("", "stone", "minecraft:", ":stone", "Minecraft:stone",
                    "minecraft:STONE", "minecraft:stone ", " minecraft:stone",
                    "minecraft:stone\n", "minecraft:sto ne", "minecraft:a:b",
                    "mine/craft:stone", "minecraft:камень"):
            for operation in (BlockSpec, normalize_block):
                with self.subTest(key=key, operation=operation.__name__):
                    with self.assertRaises(InvalidBlockError) as caught:
                        operation(key)
                    self.assertIsInstance(caught.exception, MinecraftError)
                    self.assertEqual(caught.exception.code, "INVALID_BLOCK")
                    self.assertEqual(caught.exception.outcome, "not-applied")

    def test_syntactically_valid_key_is_not_checked_against_local_registry(self) -> None:
        # Material existence and whether an item is placeable belong to Paper.
        for key in ("minecraft:oak_stairs", "minecraft:iron_sword",
                    "example:custom/block_2.test", "example-mod:future_block"):
            with self.subTest(key=key):
                self.assertEqual(normalize_block(key), BlockSpec(key))

    def test_inline_block_properties_are_explicitly_unsupported(self) -> None:
        for key in ("minecraft:oak_log[axis=x]",
                    "minecraft:oak_stairs[facing=east,half=bottom]"):
            for operation in (BlockSpec, normalize_block):
                with self.subTest(key=key, operation=operation.__name__):
                    with self.assertRaises(UnsupportedFeatureError) as caught:
                        operation(key)
                    self.assertEqual(caught.exception.code, "UNSUPPORTED_FEATURE")
                    self.assertEqual(caught.exception.outcome, "not-applied")


class BlockValueTests(unittest.TestCase):
    def test_legacy_constructor_checks_both_integer_fields(self) -> None:
        for invalid in (True, False, 4.0, "4", None, object()):
            with self.subTest(field="id", value=invalid):
                with self.assertRaises(TypeError):
                    LegacyBlock(invalid)  # type: ignore[arg-type]
            with self.subTest(field="data", value=invalid):
                with self.assertRaises(TypeError):
                    LegacyBlock(4, invalid)  # type: ignore[arg-type]

    def test_legacy_values_keep_unknown_pair_until_normalization(self) -> None:
        value = LegacyBlock(id=-1, data=-2)
        self.assertEqual((value.id, value.data), (-1, -2))
        with self.assertRaises(UnsupportedLegacyBlockError):
            normalize_block(value)

    def test_legacy_values_are_immutable(self) -> None:
        value = LegacyBlock(4)
        for attribute in ("id", "data"):
            with self.subTest(attribute=attribute):
                with self.assertRaises(AttributeError):
                    setattr(value, attribute, 1)
                with self.assertRaises(AttributeError):
                    delattr(value, attribute)
        self.assertEqual((value.id, value.data), (4, 0))

    def test_blockspec_constructor_checks_key_type(self) -> None:
        for invalid in (True, 4, None, b"minecraft:stone", object()):
            with self.subTest(value=invalid):
                with self.assertRaises(TypeError):
                    BlockSpec(invalid)  # type: ignore[arg-type]

    def test_blockspec_requires_mapping_for_states(self) -> None:
        for invalid in (None, [], (), "", 0, False):
            with self.subTest(value=invalid):
                with self.assertRaises(TypeError):
                    BlockSpec("minecraft:stone", invalid)  # type: ignore[arg-type]

    def test_nonempty_states_are_rejected_without_silently_discarding_them(self) -> None:
        with self.assertRaises(UnsupportedFeatureError) as caught:
            BlockSpec("minecraft:oak_log", {"axis": "x"})
        self.assertIsInstance(caught.exception, MinecraftError)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_FEATURE")
        self.assertEqual(caught.exception.outcome, "not-applied")

    def test_blockspec_fields_and_states_are_immutable(self) -> None:
        original_states: dict[str, str] = {}
        value = BlockSpec("minecraft:stone", original_states)
        original_states["axis"] = "x"
        self.assertEqual(dict(value.states), {})
        with self.assertRaises(TypeError):
            value.states["axis"] = "x"  # type: ignore[index]
        with self.assertRaises(AttributeError):
            value.key = "minecraft:air"  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            value.states = {}  # type: ignore[misc]
        self.assertEqual(value.key, "minecraft:stone")
        self.assertEqual(dict(value.states), {})


if __name__ == "__main__":
    unittest.main()
