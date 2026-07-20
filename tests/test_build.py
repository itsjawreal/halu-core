"""Package build tests (Phase 8 §9, §11): build a real wheel and
inspect its contents, rather than only checking the source tree --
catches anything a build-system misconfiguration might pull in that
`test_package_contents.py`'s source-tree scan wouldn't see (or vice
versa, something the source scan flags that never actually ships).

Skipped if the `build` package isn't installed (it's a `dev` extra,
not a hard runtime dependency) or building is otherwise unavailable --
CI always installs `.[dev]`, so this always runs there.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("build")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FORBIDDEN_SUBSTRINGS = (
    b"halu_web",
    b"bounty_triage_001",
    b"support_triage_001",
    b"trading_risk_001",
)


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out_dir)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def test_wheel_builds_successfully(built_wheel: Path) -> None:
    assert built_wheel.exists()


def test_wheel_contains_py_typed_marker(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()
    assert any(name.endswith("halu_core/py.typed") for name in names)


def test_wheel_contains_no_halu_web_or_hidden_challenge_data(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        for name in archive.namelist():
            if not name.endswith(".py"):
                continue
            content = archive.read(name)
            for forbidden in _FORBIDDEN_SUBSTRINGS:
                assert forbidden not in content, f"{name} contains {forbidden!r}"


def test_wheel_does_not_bundle_env_files_or_tests(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()
    assert not any(name.endswith(".env") for name in names)
    assert not any("/tests/" in name or name.startswith("tests/") for name in names)
