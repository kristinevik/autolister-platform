"""Architecture checks: the engine must never be able to sign anything.

Key isolation is enforced by IAM, but it is cheaper to keep the engine incapable
of signing than to rely on that alone. These tests fail the build if a signing
library reaches the engine's code or its image.
"""

import ast
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
SIGNING_PACKAGES = {"web3", "eth-account", "eth-keys", "eth-keyfile"}
SIGNING_MODULES = {"web3", "eth_account", "eth_keys", "eth_keyfile"}


def test_the_engine_image_contains_no_signing_library():
    lock = (SERVICE / "requirements.txt").read_text().splitlines()
    pinned = {line.split("==")[0].lower() for line in lock if "==" in line}
    assert pinned, "the lock file looks empty"
    assert not pinned & SIGNING_PACKAGES


def test_the_engine_code_imports_no_signing_library():
    for path in (SERVICE / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                assert module.split(".")[0] not in SIGNING_MODULES, f"{path}: {module}"
