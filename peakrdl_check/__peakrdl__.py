"""PeakRDL CLI integration.

Registers the ``check`` subcommand with the PeakRDL command-line tool:

    peakrdl check head.rdl --base main/design.rdl --fail-on breaking

The positional input files are compiled and elaborated by PeakRDL itself
(so every importer/compilation option PeakRDL supports applies to the head
side); the ``--base`` specification is compiled by this plugin. The two
canonical models are then compared by the semantic diff engine, a report is
emitted, and the process exits non-zero when changes at or above the
configured severity threshold are present.
"""

from types import SimpleNamespace
from typing import TYPE_CHECKING

import sys

from peakrdl.plugins.exporter import ExporterSubcommandPlugin

if TYPE_CHECKING:
    import argparse
    from systemrdl.node import AddrmapNode


class Exporter(ExporterSubcommandPlugin):
    short_desc = "Semantic compatibility check against a baseline revision"
    long_desc = (
        "Compare the elaborated register model against a baseline SystemRDL "
        "revision, classify every interface change by impact (breaking / "
        "behavioural / compatible / documentation / uncertain), and fail "
        "according to the configured severity threshold. Suitable as a CI "
        "quality gate."
    )

    # This subcommand writes a report only when asked to; no mandatory -o.
    generates_output_file = False

    def add_exporter_arguments(self, arg_group: 'argparse.ArgumentParser') -> None:
        arg_group.add_argument(
            "--base",
            required=True,
            help="baseline SystemRDL file to compare against")
        arg_group.add_argument(
            "--base-top",
            default=None,
            help="top component name in the baseline (default: auto)")
        arg_group.add_argument(
            "--format",
            choices=("text", "json", "markdown", "sarif"),
            default="text",
            help="report format (default: text)")
        arg_group.add_argument(
            "-o", "--output",
            dest="output",
            default=None,
            help="write the report to a file instead of stdout")
        arg_group.add_argument(
            "--fail-on",
            choices=("breaking", "behavioural", "validation-error", "none"),
            default="breaking",
            help="severity threshold that fails the command (default: breaking)")
        arg_group.add_argument(
            "--policy",
            default=None,
            help="path to a severity-policy override JSON")
        arg_group.add_argument(
            "--no-rename-detection",
            action="store_true",
            help="disable rename heuristics (renames report as remove+add)")

    def do_export(self, top_node: 'AddrmapNode', options: 'argparse.Namespace') -> None:
        from systemrdl import RDLCompileError

        from .adapter import StageTimings, build_canonical, canonicalize_root
        from .cli import _severity_exit
        from .diff import compile_failed_result, diff_models
        from .policy import load_policy
        from .report import FORMATTERS

        # Head: reuse the model PeakRDL already elaborated — no recompile.
        head = canonicalize_root(SimpleNamespace(top=top_node), "all",
                                 StageTimings())

        try:
            base = build_canonical([options.base], top=options.base_top,
                                   source_mode="all")
        except RDLCompileError as e:
            result = compile_failed_result("base", str(e))
        else:
            result = diff_models(
                base, head,
                policy=load_policy(options.policy),
                rename_detection=not options.no_rename_detection)

        text = FORMATTERS[options.format](result)
        if options.output:
            with open(options.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"peakrdl check: wrote {options.output} "
                  f"({result['totalChanges']} changes)")
        else:
            sys.stdout.write(text)

        if options.fail_on != "none":
            code = _severity_exit(result, options.fail_on)
            if code:
                print(f"peakrdl check: changes at or above "
                      f"'{options.fail_on}' present", file=sys.stderr)
                sys.exit(code)
