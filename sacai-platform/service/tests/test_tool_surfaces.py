"""Prevent accidental exposure of internal helper methods as model Tools."""

import importlib.util
import inspect
from pathlib import Path


def _public_methods(path: Path) -> list[str]:
    """Load a standalone Tool and return model-visible public method names.

    Tool path is the input. The output mirrors OpenWebUI's public-callable and
    non-class discovery rule closely enough to catch the prior loop regression.
    """

    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    instance = module.Tools()
    return [
        name
        for name in dir(instance)
        if not name.startswith("_") and callable(getattr(instance, name)) and not inspect.isclass(getattr(instance, name))
    ]


def test_each_tool_has_one_model_visible_entry_point() -> None:
    """Require exactly one public callable in every SACAI OpenWebUI Tool."""

    root = Path(__file__).parents[2] / "openwebui_tools"
    expected = {
        "planetir.py": ["planetir"],
        "isis3_preprocess.py": ["isis3_preprocess"],
        "admin_cleanup.py": ["sacai_cleanup"],
        "stac_catalog.py": ["stac_catalog"],
        "scientific_workflow.py": ["scientific_workflow"],
        "jupyter_runtime.py": ["jupyter_runtime"],
        "lunar_dem.py": ["lunar_dem_pipeline"],
    }
    for filename, methods in expected.items():
        assert _public_methods(root / filename) == methods
