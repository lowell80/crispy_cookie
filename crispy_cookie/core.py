"""Main module."""

import json
import sys
from pathlib import Path


class TemplateError(Exception):
    pass


class TemplateCollection:

    def __init__(self, root: Path):
        self.root = root
        self._templates = {}

    def get_template(self, name):
        if name not in self._templates:
            self._templates[name] = TemplateInfo(self.root / name)
        return self._templates[name]


class TemplateInfo:

    def __init__(self, path: Path):
        self.name = path.name
        self.path = path
        self.context_file = path / "cookiecutter.json"
        if not self.context_file.is_file():
            raise TemplateError(f"{self.context_file} is not a file!")
        candidates = [p for p in path.glob("*{{*") if p.is_dir()]
        if not candidates:
            raise TemplateError(f"Can't find the top-level project for {path}")
        if len(candidates) > 1:
            raise TemplateError(f"Found more than one top-level folder for "
                                f"project {path}.  Candidates include:"
                                f": {[str(c) for c in candidates]}")
        self.template_base = candidates[0]

    @property
    def default_context(self):
        with open(self.context_file) as f:
            return json.load(f)

