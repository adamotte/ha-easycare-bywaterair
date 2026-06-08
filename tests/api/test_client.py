"""Tests unitaires du client API (parties pures, sans réseau)."""

from __future__ import annotations

import logging

from custom_components.easycare_bywaterair.api.client import EasyCareClient
from custom_components.easycare_bywaterair.api.models import Module
from custom_components.easycare_bywaterair.const import (
    MODULE_TYPE_BPC,
    MODULE_TYPE_WATBOX,
)


def _mod(type_: str) -> Module:
    return Module(type=type_, name="X-1", id="i", serial_number="s")


class TestValidateModuleType:
    """_validate_module_type : tolère les variantes, ne lève jamais (issue #10)."""

    def test_exact_type_no_log(self, caplog):
        with caplog.at_level(logging.DEBUG):
            EasyCareClient._validate_module_type(
                _mod(MODULE_TYPE_WATBOX), MODULE_TYPE_WATBOX, "watbox"
            )
        assert caplog.text == "" or "variante" not in caplog.text

    def test_family_prefix_variant_is_debug_not_warning(self, caplog):
        # lr-bst-react : variante gateway connue → debug, pas de warning.
        with caplog.at_level(logging.DEBUG):
            EasyCareClient._validate_module_type(
                _mod("lr-bst-react"), MODULE_TYPE_WATBOX, "watbox"
            )
        assert "tolerated" in caplog.text
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_bpc_family_prefix_variant_is_debug(self, caplog):
        with caplog.at_level(logging.DEBUG):
            EasyCareClient._validate_module_type(
                _mod("lr-pc-vs2"), MODULE_TYPE_BPC, "bpc"
            )
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_bpc2_alias_lr_ph_no_warning(self, caplog):
        # lr-ph = BPC2 (alias BPC) : pas de warning malgré type != lr-pc.
        with caplog.at_level(logging.DEBUG):
            EasyCareClient._validate_module_type(
                _mod("lr-ph"), MODULE_TYPE_BPC, "bpc"
            )
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_fully_unknown_type_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            EasyCareClient._validate_module_type(
                _mod("lr-weird"), MODULE_TYPE_WATBOX, "watbox"
            )
        assert any(r.levelno >= logging.WARNING for r in caplog.records)
        assert "lr-weird" in caplog.text
