"""Tests for the keyword rules engine."""
from __future__ import annotations

import pytest

from bank_agent_llm.enrichment.rules import SignatureRules


@pytest.fixture
def rules() -> SignatureRules:
    return SignatureRules()


# ── Known merchants ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("description,expected_tag", [
    ("UBER RIDES", "uber"),
    ("DLO*DIDI", "uber"),
    ("NETFLIX", "streaming"),
    ("SPOTIFY", "streaming"),
    ("GOOGLE *PLAY YOUTUBE*D CR 7", "streaming"),
    ("INTERESES CORRIENTES", "intereses"),
    ("GMF GRAVAMEN MOVIMIENTO FINANC", "impuesto-gmf"),
    ("CUOTA DE MANEJO", "cuota-manejo"),
    ("POLIZA CARDIF", "seguro-bancario"),
    ("COBRO SEGURO VIDA DEUDOR", "seguro-bancario"),
    ("ANDRES CARNE DE RES CLL 2 1", "restaurante"),
    ("ARCHIE S COLINA CR 58B 145", "restaurante"),
    ("BW BUFFALO WINGS 140 CL 140", "restaurante"),
    ("PARQUEADERO 11 ED HHC CL 14", "parqueadero"),
    ("TIENDA D1 CALLE 80", "tienda"),
    ("OXXO PRIMAVERA CR 27 18 12", "tienda"),
    ("CURSOR USAGE MID FEB", "software"),
    ("CURSOR, AI POWERED IDE", "software"),
    ("CLAUDE.AI SUBSCRIPTION", "software"),
    ("MOVISTAR PAGOSEPAYCO TV 60", "telefonia"),
    ("SUPERMERCADO VILMAR CLL 151", "supermercado"),
    ("SUBWAY PLAZA IMPERIAL CL 10", "restaurante"),
])
def test_known_merchants(rules: SignatureRules, description: str, expected_tag: str) -> None:
    result = rules.match(description, "debit")
    assert result is not None, f"No match for: {description!r}"
    assert expected_tag in result.tags, f"Expected {expected_tag!r} in {result.tags} for {description!r}"


# ── Credit direction ──────────────────────────────────────────────────────────

def test_credit_abono_wompi(rules: SignatureRules) -> None:
    result = rules.match("ABONO WOMPI/PSE", "credit")
    assert result is not None
    assert "pago-tarjeta" in result.tags


def test_credit_pago_tarjeta_cmr(rules: SignatureRules) -> None:
    result = rules.match("PAGO TARJETA CMR", "credit")
    assert result is not None
    assert "pago-tarjeta" in result.tags


def test_credit_abono_sucursal(rules: SignatureRules) -> None:
    result = rules.match("ABONO SUCURSAL VIRTUAL", "credit")
    assert result is not None
    assert "pago-tarjeta" in result.tags


# ── Direction filter ──────────────────────────────────────────────────────────

def test_pago_tarjeta_rule_does_not_match_debit(rules: SignatureRules) -> None:
    # "ABONO WOMPI" as a debit should NOT match pago-tarjeta rule
    # (direction=credit rule should be filtered out)
    result = rules.match("ABONO WOMPI/PSE", "debit")
    # It might still match something else (or not at all), but NOT pago-tarjeta
    if result:
        assert "pago-tarjeta" not in result.tags


# ── Credit fallback ───────────────────────────────────────────────────────────

def test_credit_fallback_abono(rules: SignatureRules) -> None:
    result = rules.credit_fallback("ABONO DEBITO AUTOMATICO")
    assert "pago-tarjeta" in result.tags
    assert result.source == "direction_rule"


def test_credit_fallback_transferencia(rules: SignatureRules) -> None:
    result = rules.credit_fallback("TRANSF. A JUAN")
    assert "transferencia" in result.tags


def test_credit_fallback_unknown(rules: SignatureRules) -> None:
    result = rules.credit_fallback("ALGUNA DESCRIPCION RARA")
    assert "ingreso" in result.tags


# ── No match ─────────────────────────────────────────────────────────────────

def test_no_match_returns_none(rules: SignatureRules) -> None:
    result = rules.match("ZXQWERTY UNKNOWN MERCHANT 99999", "debit")
    assert result is None


# ── Merchant name populated ───────────────────────────────────────────────────

def test_merchant_name_set(rules: SignatureRules) -> None:
    result = rules.match("NETFLIX", "debit")
    assert result is not None
    assert result.merchant_name == "Netflix"


def test_source_is_keyword_rule(rules: SignatureRules) -> None:
    result = rules.match("UBER RIDES", "debit")
    assert result is not None
    assert result.source == "keyword_rule"
