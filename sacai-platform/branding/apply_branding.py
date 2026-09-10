"""Apply the SAC-ALRA frontend overlay to a disposable OpenWebUI build context."""

from pathlib import Path
import argparse
import json
import re


def replace_frontend_branding(source_root: Path, project_name: str) -> None:
    """Replace visible upstream names throughout frontend source and static text.

    The disposable OpenWebUI root and project name are inputs. The function
    returns nothing and edits only the container build context, leaving the
    vendored host checkout untouched for future upstream upgrades.
    """

    text_suffixes = {".svelte", ".ts", ".js", ".html", ".json", ".xml", ".css", ".webmanifest"}
    for parent in (
        source_root / "src",
        source_root / "static",
        source_root / "backend/open_webui/static",
    ):
        for path in parent.rglob("*"):
            if not path.is_file() or path.suffix not in text_suffixes:
                continue
            content = path.read_text(encoding="utf-8")
            content = content.replace("Open WebUI", project_name).replace("OpenWebUI", project_name)
            path.write_text(content, encoding="utf-8")


def replace_backend_name(source_root: Path, project_name: str) -> None:
    """Set backend default name and remove the upstream-name suffix behavior.

    The disposable source root and project name are inputs. Runtime config will
    now return the requested brand without appending the upstream product name.
    """

    path = source_root / "backend/open_webui/env.py"
    content = path.read_text(encoding="utf-8")
    content = re.sub(
        r"WEBUI_NAME = os\.getenv\('WEBUI_NAME', 'Open WebUI'\)\nif WEBUI_NAME != 'Open WebUI':\n    WEBUI_NAME \+= ' \(Open WebUI\)'",
        f"WEBUI_NAME = os.getenv('WEBUI_NAME', {project_name!r})",
        content,
    )
    content = content.replace(
        "WEBUI_FAVICON_URL = 'https://openwebui.com/favicon.png'",
        "WEBUI_FAVICON_URL = '/static/sacai-logo.svg'",
    )
    path.write_text(content, encoding="utf-8")


def harden_frontend_version_check(source_root: Path, openwebui_version: str) -> None:
    """Ensure editor version checks receive strings even if Vite metadata is absent.

    The disposable source root and the checked package version are inputs. The
    function patches only the build copy and raises when the expected upstream
    statements are missing, preventing a silent partial overlay.
    """

    constants_path = source_root / "src/lib/constants.ts"
    constants = constants_path.read_text(encoding="utf-8")
    old_constant = "export const WEBUI_VERSION = APP_VERSION;"
    if old_constant not in constants:
        raise RuntimeError("expected WEBUI_VERSION declaration was not found")
    constants = constants.replace(
        old_constant,
        "export const WEBUI_VERSION = "
        f"typeof APP_VERSION === 'string' ? APP_VERSION : {openwebui_version!r};",
        1,
    )
    constants_path.write_text(constants, encoding="utf-8")

    utils_path = source_root / "src/lib/utils/index.ts"
    utils = utils_path.read_text(encoding="utf-8")
    old_comparison = """export const compareVersion = (latest, current) => {
\treturn current === '0.0.0'
\t\t? false
\t\t: current.localeCompare(latest, undefined, {
\t\t\t\tnumeric: true,
\t\t\t\tsensitivity: 'case',
\t\t\t\tcaseFirst: 'upper'
\t\t\t}) < 0;
};"""
    new_comparison = """export const compareVersion = (latest, current) => {
\tconst latestVersion = typeof latest === 'string' ? latest : '0.0.0';
\tconst currentVersion = typeof current === 'string' ? current : '0.0.0';

\treturn currentVersion === '0.0.0'
\t\t? false
\t\t: currentVersion.localeCompare(latestVersion, undefined, {
\t\t\t\tnumeric: true,
\t\t\t\tsensitivity: 'case',
\t\t\t\tcaseFirst: 'upper'
\t\t\t}) < 0;
};"""
    if old_comparison not in utils:
        raise RuntimeError("expected compareVersion implementation was not found")
    utils_path.write_text(utils.replace(old_comparison, new_comparison, 1), encoding="utf-8")


def install_logo(source_root: Path, logo_path: Path, project_name: str) -> None:
    """Install the project SVG and point startup, auth, favicon and PWA uses to it.

    Source root, logo path and project name are inputs. The function returns
    nothing and updates the disposable build's static asset references.
    """

    for destination in (
        source_root / "static/sacai-logo.svg",
        source_root / "static/static/sacai-logo.svg",
        source_root / "backend/open_webui/static/sacai-logo.svg",
    ):
        destination.write_text(
            logo_path.read_text(encoding="utf-8").replace("SACAI", project_name),
            encoding="utf-8",
        )
    path_replacements = {
        "/static/favicon-dark.png": "/static/sacai-logo.svg",
        "/static/favicon-96x96.png": "/static/sacai-logo.svg",
        "/static/favicon.svg": "/static/sacai-logo.svg",
        "/static/favicon.ico": "/static/sacai-logo.svg",
        "/static/favicon.png": "/static/sacai-logo.svg",
        "/static/splash-dark.png": "/static/sacai-logo.svg",
        "/static/splash.png": "/static/sacai-logo.svg",
        "/favicon.png": "/static/sacai-logo.svg",
    }
    for path in (source_root / "src").rglob("*"):
        if not path.is_file() or path.suffix not in {".svelte", ".ts", ".js", ".html"}:
            continue
        content = path.read_text(encoding="utf-8")
        for old, new in path_replacements.items():
            content = content.replace(old, new)
        path.write_text(content, encoding="utf-8")
    app_path = source_root / "backend/open_webui/main.py"
    app_content = app_path.read_text(encoding="utf-8").replace("/static/logo.png", "/static/sacai-logo.svg")
    app_path.write_text(app_content, encoding="utf-8")
    manifest_path = source_root / "static/static/site.webmanifest"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["name"] = project_name
    manifest["short_name"] = project_name
    manifest["icons"] = [
        {"src": "/static/sacai-logo.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Parse CLI arguments and apply all branding steps to one build context."""

    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--project-name", default="SAC-ALRA")
    parser.add_argument("--openwebui-version", default="0.10.2")
    parser.add_argument("--logo", type=Path, required=True)
    arguments = parser.parse_args()
    replace_frontend_branding(arguments.source_root, arguments.project_name)
    replace_backend_name(arguments.source_root, arguments.project_name)
    harden_frontend_version_check(arguments.source_root, arguments.openwebui_version)
    install_logo(arguments.source_root, arguments.logo, arguments.project_name)


if __name__ == "__main__":
    main()
