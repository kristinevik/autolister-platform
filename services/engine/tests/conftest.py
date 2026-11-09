"""Fixtures. Fakes and builders live in ``tests/fakes.py``."""

from __future__ import annotations

import os

import pytest
from hypothesis import settings

from autolister_core.accounts import Account
from autolister_engine.config import Strategy

from tests.fakes import COLLECTION, OWN

# Hypothesis: quick locally, thorough in CI (which sets HYPOTHESIS_PROFILE=ci).
settings.register_profile("dev", max_examples=100, deadline=None)
settings.register_profile("ci", max_examples=1000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture
def strategy() -> Strategy:
    return Strategy(collection_address=COLLECTION)


@pytest.fixture
def account() -> Account:
    return Account(id="investor-1", address=OWN, token_ids=("101", "102"))
