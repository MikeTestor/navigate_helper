"""Command line: python -m navigate_helper clean|chunk|embed|all|ask|ui."""

import argparse
import sys

from navigate_helper import ask, chunk, clean, embed, ui
from navigate_helper.config import MissingConfigError, load_config

STAGES = {"clean": clean, "chunk": chunk, "embed": embed}
PIPELINE = ("clean", "chunk", "embed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="navigate_helper")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("clean", "chunk"):
        sub = commands.add_parser(name, help=f"run the {name} stage")
        sub.add_argument("--page", metavar="STEM", help="only this Manual Page (filename without .htm)")
    commands.add_parser("embed", help="run the embed stage")
    commands.add_parser("all", help="run clean, chunk and embed; stops on the first failure")
    ask_parser = commands.add_parser("ask", help="ask one question")
    ask_parser.add_argument("question")
    commands.add_parser("ui", help="start the Gradio dev app")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    try:
        if args.command == "all":
            for name in PIPELINE:
                print(f"== {name}", file=sys.stderr)
                STAGES[name].run(config)
        elif args.command in STAGES:
            STAGES[args.command].run(config, **({"page": args.page} if args.command != "embed" else {}))
        elif args.command == "ask":
            config.require_api_key()
            ask.run(config, question=args.question)
        elif args.command == "ui":
            config.require_api_key()
            ui.run(config)
    except (MissingConfigError, NotImplementedError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
