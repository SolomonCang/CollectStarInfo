from __future__ import annotations

import csv
from pathlib import Path


def parse_targets(targets: str | None, targets_file: str | None) -> list[str]:
    values: list[str] = []

    if targets:
        values.extend(
            [item.strip() for item in targets.split(",") if item.strip()])

    if targets_file:
        path = Path(targets_file)
        if not path.exists():
            raise FileNotFoundError(f"Targets file not found: {targets_file}")

        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    for cell in row:
                        cell = cell.strip()
                        if cell and cell.lower() not in {
                                "target", "star", "name"
                        }:
                            values.append(cell)
        else:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    name = line.strip()
                    if name:
                        values.append(name)

    deduped: list[str] = []
    seen: set[str] = set()
    for name in values:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(name)

    return deduped
