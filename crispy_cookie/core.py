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

    def list_templates(self):
        templates = [p.parent.name for p in self.root.glob("*/cookiecutter.json")]
        templates.sort()
        return templates


class TemplateInfo:

    def __init__(self, path: Path):
        self.name = path.name
        self.path = path
        self._meta = None
        self.context_file = path / "cookiecutter.json"
        self.metadata_file = path / "crispycookie.json"
        if not self.context_file.is_file():
            raise TemplateError(f"{self.context_file} is not a file!")
        if not self.metadata_file.is_file():
            raise TemplateError(f"{self.metadata_file} is not present.  "
                                "This directory is not a crispycookie template.")
        candidates = [p for p in path.glob("*{{*") if p.is_dir()]
        if not candidates:
            raise TemplateError(f"Can't find the top-level project for {path}")
        if len(candidates) > 1:
            raise TemplateError(f"Found more than one top-level folder for "
                                f"project {path}.  Candidates include:"
                                f": {[str(c) for c in candidates]}")
        self.template_base = candidates[0]
        self.parse_metadata()

    def parse_metadata(self):
        with open(self.metadata_file) as f:
            metadata = json.load(f)
        meta = {
            "extends": [],
            "inherits": [],
            "ephemeral": [],
        }
        meta["default_layer_name"] = metadata["default_layer_name"]
        meta["default_layer_mounts"] = metadata["default_layer_mounts"]
        if "extends" in metadata:
            # Only single values is supported for now, but internally make it a list
            meta["extends"] = [metadata["extends"]]
        if "inherits" in metadata:
            meta["inherits"] = [str(var) for var in metadata["inherits"]]
        if "ephemeral" in metadata:
            ephemeral = metadata["ephemeral"]
            if isinstance(ephemeral, str):
                ephemeral = [ephemeral]
            meta["ephemeral"] = [str(var) for var in ephemeral]
        self._meta = meta

    @property
    def default_context(self):
        with open(self.context_file) as f:
            return json.load(f)

    @property
    def inherits(self):
        """ inherits allows variables from a prior layer to be copied down into
        the current layer. """
        return self._meta["inherits"]

    @property
    def default_layer_name(self):
        return self._meta["default_layer_name"]

    @property
    def default_layer_mounts(self):
        return self._meta["default_layer_mounts"]

    @property
    def extends(self):
        """ extends is means to declare that one layer requires another layer.
        """
        return self._meta["extends"]

    @property
    def ephemeral(self):
        """ ephemeral values are NOT stored in the crispycookie.json file and
        therefore are re-calculated or inherited from the cookiecutter.json file
        each time a project is built.

        If the values is manually placed in the crispycookie.json file, it will
        be preserved.
        """
        return self._meta["ephemeral"]
