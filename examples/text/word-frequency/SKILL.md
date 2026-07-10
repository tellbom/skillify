---
name: word-frequency
description: Use when the user wants a word-frequency count / ranking from a block of text. Runs scripts/word_frequency.py in this skill's per-skill venv (has `tabulate` installed).
---

# Word Frequency

Count how often each word appears in a block of text and show the top results as a table.

## Steps

1. Get the text — either pasted directly or read from a file the user points at.
2. Run this skill's script inside its per-skill venv (created by `skillctl install`, path
   recorded in `~/.skillify/locks/text__word-frequency.json`):
   ```
   <venv>/bin/python scripts/word_frequency.py <path-to-text-file> [--top N]
   ```
   (On Windows: `<venv>\Scripts\python.exe`.)
3. Report the resulting table to the user. If they only pasted text inline with no file,
   write it to a temp file first.

## Notes

- Word matching is case-insensitive, alphanumeric-only (`[a-z0-9]+`), so punctuation isn't
  counted as part of a word.
- Default top-N is 10; pass `--top` to change it.
