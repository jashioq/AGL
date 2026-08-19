"""Structural test: the package tree under src/agl/ is fully importable."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "src" / "agl"


def test_every_directory_under_src_agl_is_a_package() -> None:
    """Every directory under src/agl/ must carry an __init__.py."""
    candidates = [PACKAGE_ROOT, *(p for p in PACKAGE_ROOT.rglob("*") if p.is_dir())]
    missing = sorted(
        str(d.relative_to(PACKAGE_ROOT.parent))
        for d in candidates
        if d.name != "__pycache__" and not (d / "__init__.py").is_file()
    )
    assert not missing, f"directories without __init__.py: {missing}"
