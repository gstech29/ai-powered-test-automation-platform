"""Command-line interface: ``qa-platform generate SPEC --output FILE``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qa_platform import __version__
from qa_platform.openapi_loader import SpecError, load_spec
from qa_platform.test_generator import analyse_spec, render_module


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qa-platform",
        description="Generate deterministic Pytest API tests from a local OpenAPI 3.0.x file.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    generate = subcommands.add_parser(
        "generate",
        help="generate Pytest tests for the supported GET operations in a specification",
        description=(
            "Generate one Pytest test per supported GET operation. Unsupported operations "
            "are reported and skipped. The generated tests read the target from API_BASE_URL."
        ),
    )
    generate.add_argument("spec", help="path to a local OpenAPI 3.0.x file (.yaml, .yml or .json)")
    generate.add_argument("-o", "--output", required=True, help="path of the Python test file to write")
    generate.add_argument("--force", action="store_true", help="overwrite the output file if it exists")
    generate.set_defaults(handler=_generate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


def _error(message: str) -> int:
    print(f"qa-platform: error: {message}", file=sys.stderr)
    return 1


def _generate(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    output = Path(args.output)
    if output.suffix != ".py":
        return _error(f"output file must end in .py: {output}")

    try:
        analysis = analyse_spec(load_spec(spec_path))
    except SpecError as exc:
        return _error(str(exc))

    for item in analysis.skipped:
        print(f"Skipped {item.method} {item.path}: {item.reason}", file=sys.stderr)
    if not analysis.tests:
        return _error("no supported operations found; no test file was written")

    if output.is_dir():
        return _error(f"output path is a directory: {output}")
    if output.exists():
        if output.resolve() == spec_path.resolve():
            return _error("output path is the specification file itself")
        if not args.force:
            return _error(f"output file already exists: {output} (use --force to overwrite)")

    source = render_module(analysis, spec_path.name)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w" if args.force else "x", encoding="utf-8", newline="\n") as handle:
            handle.write(source)
    except FileExistsError:
        return _error(f"output file already exists: {output} (use --force to overwrite)")
    except OSError as exc:
        return _error(f"could not write {output}: {exc.strerror or exc}")

    print(f"Generated {len(analysis.tests)} test(s) in {output}")
    return 0
