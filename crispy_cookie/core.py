"""Main module."""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

GIT_BIN = "git"


def _git_stdout(*git_args, repo):
    args = ["git"]
    args.extend(git_args)
    return subprocess.run(args, cwd=repo, stdout=subprocess.PIPE, check=True, text=True).stdout


def git_status(repo):
    c = Counter()
    stdout = _git_stdout("status", "--porcelain", "--ignored", ".", repo=repo)
    # XY:  X=index, Y=working tree.   For our simplistic approach we consider them together.
    for line in stdout.splitlines():
        state = line[0:2]
        if state == "??":
            c["untracked"] += 1
        elif state == "!!":
            c["ignored"] += 1
        else:
            c["changed"] += 1
    return c


class TemplateError(Exception):
    pass


class TemplateCollection:

    def __init__(self, root: Path):
        self.root = root
        self._templates = {}
        self._repo = None
        self._rev = None

    def get_template(self, name):
        if name not in self._templates:
            self._templates[name] = TemplateInfo(self.root / name)
        return self._templates[name]

    def list_templates(self):
        templates = [p.parent.name for p in self.root.glob("*/cookiecutter.json")]
        templates.sort()
        return templates

    @property
    def repo(self) -> str:
        if not self._repo:
            remotes = _git_stdout("remote", repo=self.root).splitlines()
            assert len(remotes) == 1, "Not coded to handle multiple remotes.  Try setting repo explicitly."
            remote = remotes[0].split()
            remotes = _git_stdout("remote", "remote", "get-url", remote,
                                  repo=self.root).splitlines()
            self._repo = remotes[0].strip()
        return self._repo

    @repo.setter
    def repo(self, value: str):
        self._repo = value

    @property
    def short_repo(self) -> str:
        """ Return simplified repo name. """
        return self.repo.strip("/").split("/")[-1].replace(".git", "")

    @property
    def rev(self) -> str:
        if not self._rev:
            self._rev = _git_stdout("rev-parse", "HEAD", repo=self.root).strip()
        return self._rev

    @rev.setter
    def rev(self, value: str):
        self._rev = value


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
        meta["default_layer_mounts"] = metadata.get("default_layer_mounts", [])
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
