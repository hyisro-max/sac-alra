"""Mission-configurable, shell-free Orfeo ToolBox (OTB) post-processing wrapper.

Same contract as isis/isis_preprocess.py and dem/asp_stereo.py: no OTB
application or parameter choice is hardcoded here. OTB_POSTPROCESS_COMMAND is
one operator-configured command template (typically an otbcli_* application,
e.g. OrthoRectification using the DEM produced by the ASP stage) run once
against the source image and the DEM.
"""

import argparse
import os
import shlex
import subprocess
from pathlib import Path


def run_stage(template: str, stage: str, **placeholders: str) -> None:
    """Run one configured OTB stage without invoking a shell."""

    if not template:
        raise RuntimeError(f"OTB_{stage.upper()}_COMMAND is not configured")
    arguments = [part.format(**placeholders) for part in shlex.split(template)]
    completed = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{stage} failed: {completed.stderr[-4000:]}")


def postprocess(source: Path, dem: Path, destination: Path) -> None:
    """Run the configured OTB stage against one source image and one DEM.

    Source image, DEM (e.g. from the ASP stage), and final destination are
    inputs. Intermediate OTB files stay in the job's own output directory;
    only the final destination is validated here.
    """

    run_stage(
        os.environ.get("OTB_POSTPROCESS_COMMAND", ""),
        "postprocess",
        input=str(source),
        dem=str(dem),
        output=str(destination),
    )


def main() -> None:
    """Parse input/dem/output CLI arguments and run the configured OTB stage."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dem", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    postprocess(arguments.input.resolve(), arguments.dem.resolve(), arguments.output.resolve())


if __name__ == "__main__":
    main()
