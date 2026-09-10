"""Verify the disposable frontend overlay before Vite compiles it."""

from pathlib import Path
import argparse


def verify_overlay(source_root: Path, expected_version: str) -> None:
    """Validate version guards and logo assets in one patched OpenWebUI tree.

    The patched source root and expected OpenWebUI version are inputs. The
    function returns nothing and raises with a targeted error when the build
    would reproduce the Tool Save crash or missing-logo failure.
    """

    constants = (source_root / "src/lib/constants.ts").read_text(encoding="utf-8")
    utilities = (source_root / "src/lib/utils/index.ts").read_text(encoding="utf-8")
    if f"APP_VERSION : {expected_version!r}" not in constants:
        raise RuntimeError("WEBUI_VERSION has no checked fallback")
    if "typeof current === 'string'" not in utilities:
        raise RuntimeError("compareVersion is not null-safe")
    if "current.localeCompare(" in utilities:
        raise RuntimeError("unsafe compareVersion call remains")
    for path in (
        source_root / "static/static/sacai-logo.svg",
        source_root / "backend/open_webui/static/sacai-logo.svg",
    ):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"required logo asset is missing: {path}")


def main() -> None:
    """Parse the build-tree arguments and run overlay verification."""

    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--expected-version", required=True)
    arguments = parser.parse_args()
    verify_overlay(arguments.source_root, arguments.expected_version)


if __name__ == "__main__":
    main()
