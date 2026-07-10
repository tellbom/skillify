"""Count word frequency in a text file and print a ranked table (uses `tabulate`)."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from tabulate import tabulate

_WORD_RE = re.compile(r"[a-z0-9]+")


def count_words(text: str) -> Counter:
    return Counter(_WORD_RE.findall(text.lower()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text_file", type=Path, help="Path to a text file to analyze.")
    parser.add_argument("--top", type=int, default=10, help="How many top words to show.")
    args = parser.parse_args()

    text = args.text_file.read_text(encoding="utf-8")
    counts = count_words(text)
    rows = counts.most_common(args.top)
    print(tabulate(rows, headers=["word", "count"]))


if __name__ == "__main__":
    main()
