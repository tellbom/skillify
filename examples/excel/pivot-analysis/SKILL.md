---
name: pivot-analysis
description: Use when the user has tabular/CSV-like data and wants it summarized as a pivot table — grouped, aggregated (sum/count/avg), and presented as a readable table.
---

# Pivot Analysis

Given tabular data (pasted CSV/TSV, a described dataset, or a file the agent can read),
produce a pivot-table-style summary.

## Steps

1. Identify the rows/columns available and ask the user (or infer from context) which
   column(s) to group by and which column(s) to aggregate, and how (sum, count, average,
   min, max).
2. Group the data accordingly. For anything beyond a a few dozen rows pasted inline, prefer
   writing and running a short script (e.g. using `csv` + `collections.Counter`/manual
   aggregation, or `pandas` if already available in the environment) over doing arithmetic
   by hand.
3. Present the result as a markdown table: group keys as rows, aggregated metrics as
   columns. Sort by the primary group key unless the user asked for a different order.
4. If the source data is ambiguous (e.g. duplicate rows, missing values), state the
   assumption you made rather than silently guessing.

## Example

Input: a list of orders with `region, product, amount`.
Ask/infer: group by `region`, aggregate `amount` as sum.
Output: a table of region -> total amount, sorted descending by total.
