"""Argument definitions shared by the two map commands."""

from argparse import ArgumentParser
from pathlib import Path

# Commands are intended to run from a source checkout with the bundled data.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def add_basemap_arguments(parser: ArgumentParser) -> None:
    """Give both commands the same grayscale basemap options and defaults."""
    parser.add_argument(
        "--basemap-image",
        type=Path,
        default=PROJECT_ROOT / "assets" / "oxford_basemap.png",
        help="Path to the locally rendered basemap PNG",
    )
    parser.add_argument(
        "--basemap-metadata",
        type=Path,
        default=PROJECT_ROOT / "assets" / "oxford_basemap.json",
        help="Path to the basemap JSON containing geographic image bounds",
    )
