import json
import os
from contextlib import contextmanager
from pathlib import Path
from subprocess import PIPE, Popen, check_call, run
from types import FunctionType

from .core import TemplateCollection, TemplateError, TemplateInfo

GIT_BIN = "git"


class GitError(Exception):
    pass


@contextmanager
def use_git_worktree(path: Path, worktree_name: str, branch: str):
    # XXX: Find variations of worktree_name (prefix) until an unused dir is found...
    # worktree add TEMPLATE_UPDATE cookiecutter
    worktree_dir = path / worktree_name
    if worktree_dir.is_dir():
        raise GitError(f"Worktree dir already exists.  "
                       f"Please remove {worktree_dir} and try again.")

    cwd = os.getcwd()
    try:
        check_call([GIT_BIN, "worktree", "add", worktree_name, branch],
                   cwd=os.fspath(path))
        os.chdir(worktree_dir)
        yield worktree_dir
    finally:
        # Code to release resource, e.g.:
        # git worktree remove worktree_dir --force
        check_call([GIT_BIN, "worktree", "remove", worktree_name, "--force"],
                   cwd=os.fspath(path))
        os.chdir(cwd)


def upgrade_project(template_collection: TemplateCollection, project_dir: Path,
                    branch: str, config_file: Path, build_function: FunctionType,
                    verbose=True, remote_ops=None):
    from .cli import build_project

    # set working directory to root of repo
    upgrade_worktree_name = "TEMPLATE_UPDATE"

    if remote_ops:
        # git fetch --all
        check_call([GIT_BIN, "fetch", "--all"])
        # XXX: Branch not up-to-date with remote, abort!

    # XXX: Local tree not clean, abort!
    # git worktree add TEMPLATE_UPDATE cookiecutter

    with use_git_worktree(project_dir, "TEMPLATE_UPDATE", branch) as workdir:
        print("Cleaning up existing content")
        # git ls-files | xargs rm
        proc = Popen([GIT_BIN, "ls-files"], stdout=PIPE)
        stdout, stderr = proc.communicate()
        for file_name in stdout.splitlines():
            os.unlink(file_name)

        # Remove empty directories
        for (dirpath, dirnames, filenames) in os.walk(".", topdown=False):
            if ".git" in dirpath:
                continue
            if not dirnames and not filenames:
                os.rmdir(dirpath)

        # Copy in .crispycookie.json (virtually)
        with open(config_file) as fp:
            config = json.load(fp)

        # XXX: Check to see if crispycookie.json has changed 'git status --porcelain .crispycookie.json (and update commit message accordingly)
        # Show git diff of .crispycookie.json?   (In which case, writing to disk would be helpful)

        build_project(template_collection, workdir, config, verbose=verbose,
                      overwrite=True)

        print("Git add")
        # git add . && pre-commit run --all || git add .
        check_call([GIT_BIN, "add", "--all", "."])

        # XXX: Add while loop to keep running pre-commit and git add until pre-commit returns a 0 exit code.  This needs a limit as well.  Maybe pre-commit exit codes can indicated permanent failure vs temp failure.
        #     Re-ordering the pre-commit rules to run a given ord has

        loop_limit = 3
        while loop_limit:
            print("Pre-running pre-commit")
            '''
            Popen(["pre-commit", "run", "--all"])
            rc = proc.wait(timeout=30)
            '''
            rc = run(["pre-commit", "run", "--all"], timeout=30).returncode
            print(f"Completed pre-commit with rc={rc}")
            if rc == 0:
                break
            print("Git add")
            check_call([GIT_BIN, "add", "--all", "."])
            loop_limit -= 1
        if not loop_limit:
            print("Unable to get pre-commit job to finish successfully after multiple attempts")
            return

        # git status
        check_call([GIT_BIN, "status"])

        repo_short = template_collection.repo.split("/")[-1]
        rev = template_collection.rev

        print("Commiting....")
        # git commit -am "Update to cypress-cookiecutter@vX.Y.Z"
        # Disabling an hooks via --no-verify because any pre-commit work should have been done already by this point.
        check_call([GIT_BIN, "commit", "--no-verify",
                    "-m", f"Update to {repo_short}@{rev}"])

    # git push
