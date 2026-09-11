"""Mission-configurable, shell-free super-resolution wrapper (SR4RS-based).

Same contract as isis/isis_preprocess.py, dem/asp_stereo.py, and
dem/otb_postprocess.py: this script hardcodes no SR4RS command, savedmodel
path, tile size, or padding. SUPERRES_COMMAND (distinct from the outer,
constant SACAI_SUPERRES_COMMAND that invokes this script -- same two-layer
split as ISIS_INGEST_COMMAND vs SACAI_ISIS_COMMAND, or
OTB_POSTPROCESS_COMMAND vs SACAI_OTB_COMMAND) is one operator-configured
command template (the sacai-super-res image's own sr.py invocation, per
https://github.com/remicres/sr4rs, with whatever --savedmodel/--pad/--ts
flags this deployment's trained model needs already baked into the
template) run once against one input image.
"""

import argparse
import os
import shlex
import subprocess
from pathlib import Path


def run_stage(template: str, source: Path, destination: Path) -> None:
    """Run the configured super-resolution command without invoking a shell.

    Command template, source image, and destination path are inputs. The
    function returns nothing and raises with bounded stderr on failure.
    """

    if not template:
        raise RuntimeError("SUPERRES_COMMAND is not configured")
    arguments = [part.format(input=str(source), output=str(destination)) for part in shlex.split(template)]
    completed = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"super-resolution failed: {completed.stderr[-4000:]}")


def main() -> None:
    """Parse input/output CLI arguments and run the configured super-resolution command."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run_stage(
        os.environ.get("SUPERRES_COMMAND", ""),
        arguments.input.resolve(),
        arguments.output.resolve(),
    )


if __name__ == "__main__":
    main()
