from __future__ import annotations

import os

from hypothesis import settings

# Hypothesis: quick locally, thorough in CI (which sets HYPOTHESIS_PROFILE=ci).
settings.register_profile("dev", max_examples=100, deadline=None)
settings.register_profile("ci", max_examples=1000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
