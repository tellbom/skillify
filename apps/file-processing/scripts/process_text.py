from __future__ import annotations

import argparse
from pathlib import Path

from skillify.apps.file_processing import process_text


parser = argparse.ArgumentParser()
parser.add_argument("input", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--top", type=int, default=20)
args = parser.parse_args()
process_text(args.input, args.output, top=args.top)
