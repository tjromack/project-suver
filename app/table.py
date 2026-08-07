"""Tabular parsing for the Data & Analysis platform — CSV / TSV / a pasted table → a typed `TableData`.

Kept deliberately lean (stdlib `csv` only, no pandas): a table is headers + string rows + the set of columns that
read as numbers. The Data tools plan over the schema and **compute deterministically** over these rows — the model
never does the arithmetic, so the numbers are always right and every answer traces to real cells.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field

_NUM_RX = re.compile(r"^-?\(?\$?\s?\d[\d,]*(?:\.\d+)?\)?%?$")


def to_number(cell: str) -> float | None:
    """Parse a cell as a number, tolerating $ , % and (parenthesised negatives). None if it isn't numeric."""
    s = (cell or "").strip()
    if not s or not _NUM_RX.match(s):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.replace("(", "").replace(")", "").replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


@dataclass
class ColumnProfile:
    name: str
    kind: str                       # "number" | "text"
    filled: int
    missing: int
    minimum: float | None = None    # numeric
    maximum: float | None = None
    mean: float | None = None
    total: float | None = None
    distinct: int | None = None     # text
    top: list = field(default_factory=list)   # [(value, count), ...]


@dataclass
class TableData:
    headers: list[str]
    rows: list[list[str]]                       # raw string cells (the user's data, kept local)
    numeric_cols: set[int] = field(default_factory=set)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return len(self.headers)

    def col_index(self, name: str) -> int:
        """Resolve a column name to its index — exact (case-insensitive) first, then a fuzzy contains match."""
        want = (name or "").strip().lower()
        if not want:
            return -1
        for i, h in enumerate(self.headers):
            if h.strip().lower() == want:
                return i
        for i, h in enumerate(self.headers):
            hl = h.strip().lower()
            if hl and (want in hl or hl in want):
                return i
        return -1

    def numbers(self, i: int) -> list[float | None]:
        return [to_number(r[i]) if i < len(r) else None for r in self.rows]

    def schema_text(self) -> str:
        return "\n".join(
            f'- "{h}" ({"number" if i in self.numeric_cols else "text"})' for i, h in enumerate(self.headers))

    def profile(self, top_k: int = 3) -> list[ColumnProfile]:
        """A deterministic per-column profile — the trusted, computed facts a data summary is built from. Numeric
        columns get min/max/mean/total; text columns get distinct count + the top values; both get a missing count."""
        out: list[ColumnProfile] = []
        for i, h in enumerate(self.headers):
            cells = [(r[i] if i < len(r) else "").strip() for r in self.rows]
            nonempty = [c for c in cells if c]
            missing = self.n_rows - len(nonempty)
            if i in self.numeric_cols:
                nums = [n for n in self.numbers(i) if n is not None]
                out.append(ColumnProfile(
                    name=h, kind="number", filled=len(nonempty), missing=missing,
                    minimum=min(nums) if nums else None, maximum=max(nums) if nums else None,
                    mean=(sum(nums) / len(nums)) if nums else None, total=sum(nums) if nums else None))
            else:
                counts = Counter(nonempty)
                out.append(ColumnProfile(
                    name=h, kind="text", filled=len(nonempty), missing=missing,
                    distinct=len(counts), top=counts.most_common(top_k)))
        return out

    def sample_text(self, n: int = 5) -> str:
        head = " | ".join(self.headers)
        body = "\n".join(" | ".join(r) for r in self.rows[:n])
        return f"{head}\n{body}"


def _sniff_delim(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        for d in ("\t", ";", "|", ","):
            if d in sample:
                return d
        return ","


def parse_table(text: str) -> TableData | None:
    """Parse CSV/TSV/pasted tabular text → `TableData`, or None if it isn't a table (needs a header + ≥1 data row).
    Detects the delimiter and which columns are numeric (≥60% of non-empty cells parse as numbers)."""
    text = (text or "").strip()
    if not text:
        return None
    delim = _sniff_delim("\n".join(text.splitlines()[:20]))
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [[c.strip() for c in r] for r in reader if any(c.strip() for c in r)]
    if len(rows) < 2:
        return None
    headers = rows[0]
    ncol = len(headers)
    data = [(r + [""] * (ncol - len(r)))[:ncol] for r in rows[1:]]
    numeric: set[int] = set()
    for i in range(ncol):
        vals = [r[i] for r in data if i < len(r) and r[i].strip()]
        if vals and sum(1 for v in vals if to_number(v) is not None) >= max(1, int(0.6 * len(vals))):
            numeric.add(i)
    return TableData(headers=headers, rows=data, numeric_cols=numeric)
