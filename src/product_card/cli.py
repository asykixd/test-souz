import argparse
import json
import os
import sys
from pathlib import Path

from .card import Candidates, render_card
from .openai import DEFAULT_MODEL, APIError, choose_plan
from .product import InputError, Product

MAX_INPUT_BYTES = 65_536


def _read_input(path: str) -> str:
    if path == "-":
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    else:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise InputError("Input JSON must be at most 64 KiB.")
    return raw.decode("utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit status."""
    parser = argparse.ArgumentParser(description="Draft a B2B product card in Russian.")
    parser.add_argument("input", help="UTF-8 JSON file, or - for standard input")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    try:
        product = Product.from_json(_read_input(args.input))
    except UnicodeDecodeError:
        print("Input error: the file must use UTF-8 encoding.", file=sys.stderr)
        return 2
    except (InputError, OSError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("Configuration error: set OPENAI_API_KEY.", file=sys.stderr)
        return 2
    model = os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
    candidates = Candidates.from_product(product)
    try:
        plan = choose_plan(product, candidates, key, model)
    except APIError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 1

    card = render_card(product, candidates, plan)
    if args.format == "json":
        print(json.dumps(card.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(card.to_markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
