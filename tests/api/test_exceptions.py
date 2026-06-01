"""Tests de la hiérarchie d'exceptions EasyCare."""

from __future__ import annotations

import pytest

from custom_components.easycare_bywaterair.api.exceptions import (
    EasyCareApiError,
    EasyCareAuthError,
    EasyCareConnectionError,
    EasyCareError,
    EasyCareInvalidCredentialsError,
    EasyCareInvalidResponseError,
    EasyCareLoginError,
    EasyCareTimeoutError,
    EasyCareTokenExpiredError,
    EasyCareUnauthorizedError,
)


def test_exception_hierarchy_invalid_credentials():
    err = EasyCareInvalidCredentialsError("bad pass")
    assert isinstance(err, EasyCareAuthError)
    assert isinstance(err, EasyCareError)
    assert isinstance(err, Exception)


def test_exception_hierarchy_token_expired():
    err = EasyCareTokenExpiredError("expired")
    assert isinstance(err, EasyCareAuthError)
    assert isinstance(err, EasyCareError)


def test_exception_hierarchy_network_errors():
    assert issubclass(EasyCareConnectionError, EasyCareError)
    assert issubclass(EasyCareTimeoutError, EasyCareError)
    assert issubclass(EasyCareInvalidResponseError, EasyCareError)
    assert issubclass(EasyCareLoginError, EasyCareAuthError)
    assert issubclass(EasyCareUnauthorizedError, EasyCareAuthError)


def test_api_error_str_with_body():
    err = EasyCareApiError("requête échouée", status_code=500, body="Internal Server Error")
    s = str(err)
    assert "500" in s
    assert "Internal Server Error" in s
    assert "requête échouée" in s


def test_api_error_str_without_body():
    err = EasyCareApiError("not found", status_code=404)
    s = str(err)
    assert "404" in s
    assert "not found" in s


def test_api_error_body_truncated_at_500_chars():
    long_body = "x" * 1000
    err = EasyCareApiError("err", status_code=500, body=long_body)
    assert err.body is not None
    assert len(err.body) == 500


def test_api_error_none_body():
    err = EasyCareApiError("err", status_code=400, body=None)
    assert err.body is None
    assert "400" in str(err)
