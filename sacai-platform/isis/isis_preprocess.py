"""Mission-configurable, shell-free ISIS3 ingest/calibrate/project wrapper."""

import argparse
import os
import shlex
import subprocess
from pathlib import Path


def run_stage(template: str, source: Path, destination: Path, stage: str) -> None:
    """Run one configured ISIS stage without invoking a shell.

    Command template, source/destination paths and stage name are inputs. The
    function returns nothing and raises with bounded stderr on failure.
    """

    if not template:
        raise RuntimeError(f"ISIS_{stage.upper()}_COMMAND is not configured")
    arguments = [part.format(input=str(source), output=str(destination)) for part in shlex.split(template)]
    completed = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{stage} failed: {completed.stderr[-4000:]}")


def preprocess(source: Path, destination: Path) -> None:
    """Run mission-specific ingest, calibration, SPICE, and projection stages.

    Raw source and final GeoTIFF destination are inputs. Intermediate ISIS cubes
    remain in the job directory, and the final output is returned by creation.
    """

    work = destination.parent
    ingested = work / "ingested.cub"
    calibrated = work / "calibrated.cub"
    spiced = work / "spiced.cub"
    run_stage(os.environ.get("ISIS_INGEST_COMMAND", ""), source, ingested, "ingest")
    run_stage(os.environ.get("ISIS_CALIBRATE_COMMAND", ""), ingested, calibrated, "calibrate")
    run_stage(os.environ.get("ISIS_SPICE_COMMAND", ""), calibrated, spiced, "spice")
    run_stage(os.environ.get("ISIS_PROJECT_COMMAND", ""), spiced, destination, "project")


def main() -> None:
    """Parse input/output CLI arguments and run the configured ISIS pipeline."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    preprocess(arguments.input.resolve(), arguments.output.resolve())


if __name__ == "__main__":
    main()

