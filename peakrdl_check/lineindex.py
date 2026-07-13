"""Fast source line/column resolution.

systemrdl-compiler's ``DirectSourceRef._extract_line_info`` re-reads the
source file from the beginning for every lookup, which is O(file size) per
reference. This module builds one line-start offset table per file and
resolves (line, column) with a binary search — O(log lines) per lookup after
a single O(file size) scan.

It uses the resolved ``path`` plus the file-local character offset that
systemrdl-compiler exposes after segment-map resolution. Offsets are in
*characters* (the compiler opens files as utf-8 text), so the scan below also
decodes utf-8. A safe fallback to the upstream slow path exists in the
adapter if internals change.
"""

from __future__ import annotations

from bisect import bisect_right


class SourceLineIndex:
    """Per-file line-start tables with bisect lookup."""

    def __init__(self) -> None:
        self._tables: dict[str, list[int]] = {}

    def _table(self, path: str) -> list[int]:
        table = self._tables.get(path)
        if table is None:
            starts = [0]
            pos = 0
            with open(path, "r", newline="", encoding="utf-8") as fp:
                for line in fp:
                    pos += len(line)
                    starts.append(pos)
            table = starts
            self._tables[path] = table
        return table

    def resolve(self, path: str, char_offset: int) -> tuple[int, int]:
        """Return (1-based line, 1-based column) for a character offset."""
        table = self._table(path)
        idx = bisect_right(table, char_offset) - 1
        if idx < 0:
            idx = 0
        return idx + 1, char_offset - table[idx] + 1
