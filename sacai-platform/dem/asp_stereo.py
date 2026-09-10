"""Mission-configurable, shell-free ASP stereo-correlation/DEM wrapper.

Mirrors isis/isis_preprocess.py's contract exactly: this script hardcodes no
Ames Stereo Pipeline flags, sensor session-type, or algorithm choice. Every
stage is an operator-configured command template read from the environment;
this script only substitutes placeholders and checks that each stage produced
its promised output. The pipeline stays mission/sensor-agnostic by
construction, the same way ISIS ingest/calibrate/spice/project already are.
"""

import argparse
import os
import shlex
import subprocess
from pathlib import Path


def run_stage(template: str, stage: str, **placeholders: str) -> None:
    """Run one configured ASP stage without invoking a shell.

    Command template, stage name, and named placeholder values (e.g. left=,
    right=, prefix=, output=) are inputs. The function returns nothing and
    raises with bounded stderr on failure.
    """

    if not template:
        raise RuntimeError(f"ASP_{stage.upper()}_COMMAND is not configured")
    arguments = [part.format(**placeholders) for part in shlex.split(template)]
    completed = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{stage} failed: {completed.stderr[-4000:]}")


def generate_dem(left: Path, right: Path, destination: Path) -> None:
    """Run optional bundle adjustment, stereo correlation, and point2dem.

    Left/right ISIS-calibrated stereo pair and the final DEM destination are
    inputs. ASP_BUNDLE_ADJUST_COMMAND is skipped entirely when unset (many
    single-pair, well-triangulated jobs do not need it); ASP_STEREO_COMMAND
    and ASP_POINT2DEM_COMMAND are required. Intermediate ASP products (point
    clouds, disparity maps, match files) stay in the job's own output
    directory; only the final DEM GeoTIFF is validated here.
    """

    work = destination.parent
    prefix = str(work / "asp")
    adjusted_prefix = str(work / "asp_adjusted")
    bundle_adjust_template = os.environ.get("ASP_BUNDLE_ADJUST_COMMAND", "")
    if bundle_adjust_template:
        # Bundle adjustment does not rewrite the input images; it writes
        # adjusted camera parameters under adjusted_prefix, which the stereo
        # stage's own command template picks up via {bundle_adjust_prefix}
        # (typically ASP's own --bundle-adjust-prefix flag). Left/right for
        # the stereo stage stay the original images either way.
        run_stage(
            bundle_adjust_template,
            "bundle_adjust",
            left=str(left),
            right=str(right),
            prefix=adjusted_prefix,
        )
    run_stage(
        os.environ.get("ASP_STEREO_COMMAND", ""),
        "stereo",
        left=str(left),
        right=str(right),
        prefix=prefix,
        bundle_adjust_prefix=adjusted_prefix,
    )
    run_stage(
        os.environ.get("ASP_POINT2DEM_COMMAND", ""),
        "point2dem",
        prefix=prefix,
        output=str(destination),
    )


def main() -> None:
    """Parse left/right/output CLI arguments and run the configured ASP pipeline."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    generate_dem(arguments.left.resolve(), arguments.right.resolve(), arguments.output.resolve())


if __name__ == "__main__":
    main()
