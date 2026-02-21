# Project: CSV Dashboard

## Overview
A Python CLI tool that reads a CSV file, computes summary statistics, and generates a standalone HTML report with interactive charts (using embedded Chart.js). The user opens the HTML file in a browser to explore their data.

## Functional Requirements

### FR-1: Parse CSV File
Read a CSV file into a structured format. Auto-detect numeric vs categorical columns.

- Input: `path: str` (path to CSV file)
- Output: dict with `columns` (list of column metadata), `rows` (list of dicts), `row_count` (int)
- Must handle: missing values, quoted fields, different delimiters (comma, tab, semicolon)
- Must raise `FileNotFoundError` for missing files and `ValueError` for unparseable files

### FR-2: Compute Summary Statistics
For each numeric column: count, mean, median, min, max, std dev.
For each categorical column: count, unique count, top 3 most frequent values.

- Input: parsed data from FR-1
- Output: dict mapping column name to its stats dict

### FR-3: Generate HTML Report
Produce a single self-contained HTML file with:
- A summary table showing statistics for each column
- A bar chart for each categorical column (top 10 values)
- A histogram for each numeric column
- Chart.js loaded from CDN (`https://cdn.jsdelivr.net/npm/chart.js`)
- Clean, readable layout with a title showing the source filename

### FR-4: CLI Entry Point
`python -m csv_dashboard <input.csv> [--output report.html]`
- Default output filename: `<input_basename>_report.html`
- Print a summary line to stdout: `Report generated: <output_path> (N rows, M columns)`

## API Specification
```python
def parse_csv(path: str) -> dict:
    """Parse a CSV file and return structured data with column metadata."""
    ...

def compute_stats(data: dict) -> dict:
    """Compute summary statistics for each column."""
    ...

def generate_report(data: dict, stats: dict, title: str) -> str:
    """Generate a self-contained HTML report string."""
    ...

def main(input_path: str, output_path: str | None = None) -> str:
    """Full pipeline: parse, compute, generate, write. Returns output path."""
    ...
```

## Edge Cases
- Empty CSV (headers only, no data rows)
- CSV with only one column
- Columns with all missing values
- Very large CSV (100,000+ rows)
- Non-UTF-8 encoding
- Column names with special characters
