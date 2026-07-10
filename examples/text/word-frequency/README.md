# text/word-frequency

A python-backed Claude Agent Skill: given a block of text, counts word frequency and prints
a ranked table using [`tabulate`](https://pypi.org/project/tabulate/) (declared in
`skill.yaml`'s `dependencies.python`, installed into this skill's own venv by `skillctl
install`).

## Install

```
skillctl install text/word-frequency
```

This creates `~/.skillify/venvs/text__word-frequency` and installs `tabulate` into it —
nothing is installed into your system/global Python.

## Try it

```
<venv>/bin/python scripts/word_frequency.py some.txt --top 5
```
