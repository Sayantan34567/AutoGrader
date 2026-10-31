"""Shared run context handed to every analyzer."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Context:
    root: Path              # project root; relative paths in rules.json resolve here
    src: Path               # the submission (.c file)
    source: str             # its text
    binary: Path | None     # -O2 binary from the first pass (None if it did not compile)
    workdir: Path           # private scratch directory for this run
    rules: dict             # the validated rules.json content
    ref: object             # trusted reference module (problems/<x>.py)
    llm: object             # llm.OllamaClient
    first_pass: dict = field(default_factory=dict)

    @property
    def time_limit(self):
        return float(self.rules["time_limit_s"])

    @property
    def mem_mb(self):
        return int(self.rules["memory_limit_mb"])

    @property
    def statement(self):
        return self.rules["problem"]["statement"]

    @property
    def tests_dir(self):
        return self.resolve(self.rules["problem"].get("tests_dir", "tests/"))

    def resolve(self, rel):
        p = Path(rel)
        return p if p.is_absolute() else self.root / p


def load_reference(path):
    spec = importlib.util.spec_from_file_location("reference_solution", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
