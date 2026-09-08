"""Guards against dependency pins drifting apart across files.

A dependency bump edits `pyproject.toml`, but two other places carry the same
version and are not updated with it: `uv.lock`, and the Dockerfile's explicit
re-pin of pydantic after AgentCat is installed. `uv sync` re-resolves silently,
so nothing in the test suite noticed when they diverged.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
UV_LOCK = REPO_ROOT / "uv.lock"


def _pyproject_pin(package: str) -> str:
    """The exact version pinned for a package in pyproject's dependencies."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    for entry in data["project"]["dependencies"]:
        match = re.fullmatch(rf"{re.escape(package)}==([0-9][^,\s]*)", entry.strip())
        if match:
            return match.group(1)
    raise AssertionError(f"{package} is not pinned with == in pyproject.toml")


def _locked_version(package: str) -> str:
    """The version uv.lock resolves a package to."""
    text = UV_LOCK.read_text(encoding="utf-8")
    match = re.search(rf'^name = "{re.escape(package)}"\nversion = "([^"]+)"', text, re.MULTILINE)
    assert match, f"{package} not found in uv.lock"
    return match.group(1)


def _dockerfile_pins(package: str) -> list[str]:
    """Every explicit `package==version` the Dockerfile installs."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    return re.findall(rf"{re.escape(package)}==([0-9][^\s\"']*)", text)


@pytest.mark.unit
class TestPydanticPinsAgree:
    """pydantic is pinned in three places and all three must say the same thing."""

    def test_dockerfile_repin_matches_pyproject(self):
        # The Dockerfile reinstalls pydantic after AgentCat to restore the
        # project's pin. If it names an older version it silently downgrades
        # the shipped image below what pyproject requires.
        expected = _pyproject_pin("pydantic")
        found = _dockerfile_pins("pydantic")

        assert found, "expected the Dockerfile to pin pydantic explicitly"
        assert found == [expected] * len(found), (
            f"Dockerfile pins pydantic=={found} but pyproject pins {expected}. "
            f"The container would run a different version than the project declares."
        )

    def test_lockfile_matches_pyproject(self):
        # uv sync re-resolves rather than failing, so a stale lock is invisible
        # in local runs. CI also enforces this with `uv lock --check`; this test
        # gives the same signal without needing the uv binary.
        assert _locked_version("pydantic") == _pyproject_pin("pydantic")


@pytest.mark.unit
class TestPinHelpersReadWhatTheyClaim:
    """The guards above are only meaningful if the parsing actually works."""

    def test_pyproject_pin_is_found_and_looks_like_a_version(self):
        assert re.fullmatch(r"[0-9]+\.[0-9]+(\.[0-9]+)?", _pyproject_pin("pydantic"))

    def test_dockerfile_pin_is_found(self):
        assert _dockerfile_pins("pydantic")

    def test_unpinned_package_raises_rather_than_passing_silently(self):
        # A package listed with >= must not be mistaken for a pinned one, or
        # the guard would quietly compare nothing.
        with pytest.raises(AssertionError):
            _pyproject_pin("cryptography")
