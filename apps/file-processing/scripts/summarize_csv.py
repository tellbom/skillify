from __future__ import annotations

import argparse
from pathlib import Path

from skillify.apps.file_processing import summarize_csv


parser = argparse.ArgumentParser()
parser.add_argument("input", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--group-by", required=True)
parser.add_argument("--value", required=True)
parser.add_argument("--operation", choices=("sum", "count", "average"), default="sum")
args = parser.parse_args()
summarize_csv(
    args.input, args.output,
    group_by=args.group_by, value_column=args.value, operation=args.operation,
)
