"""Configuration loading and project paths.

Paths are relative to the project root: the INSIDERLAB_ROOT environment variable if set,
otherwise the current working directory. Run the CLI from the repository root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def raw_sec(self) -> Path:
        return self.data / "sec_raw"

    @property
    def sec(self) -> Path:
        return self.data / "sec"

    @property
    def prices(self) -> Path:
        return self.data / "prices"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def results(self) -> Path:
        return self.reports / "results"

    @property
    def figures(self) -> Path:
        return self.reports / "figures"

    @property
    def ledger(self) -> Path:
        return self.root / "ledger"


def paths(root: str | Path | None = None) -> Paths:
    root = Path(root or os.environ.get("INSIDERLAB_ROOT") or Path.cwd()).resolve()
    return Paths(root)


def load_config(path: str | Path | None = None, root: str | Path | None = None) -> dict:
    path = Path(path) if path else paths(root).root / "configs" / "base.yaml"
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)
