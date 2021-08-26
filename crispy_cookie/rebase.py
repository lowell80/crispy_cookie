import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from subprocess import PIPE, CalledProcessError, Popen, run
from types import FunctionType

from .core import GIT_BIN, TemplateCollection, TemplateError, TemplateInfo, git_status


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
        run([GIT_BIN, "worktree", "add", worktree_name, branch],
            cwd=os.fspath(path), check=True)
        os.chdir(worktree_dir)
        yield worktree_dir.absolute()
    finally:
        os.chdir(cwd)
        # git worktree remove worktree_dir --force
        if "CRISPYCOOKIE_NO_CLEANUP" in os.environ:
            print("Skipping cleanup of worktree due to env var.")
        else:
            try:
                run([GIT_BIN, "worktree", "remove", worktree_name, "--force"],
                    cwd=os.fspath(path), check=True)
            except CalledProcessError as e:
                print("Failure during worktree cleanup.")
                raise e


def upgrade_project(template_collection: TemplateCollection, project_dir: Path,
                    branch: str, config_file: Path, build_function: FunctionType,
                    verbose=True, remote_ops=None):
    from .cli import build_project

    # set working directory to root of repo
    upgrade_worktree_name = "TEMPLATE_UPDATE"

    print(
        f"Upgrading project to {template_collection.repo} @ {template_collection.rev} using temporary working tree {upgrade_worktree_name}")

    if remote_ops:
        # git fetch --all
        run([GIT_BIN, "fetch", "--all"], check=True)
        # XXX: Branch not up-to-date with remote, abort!

    status = git_status(project_dir)
    if status["changed"] > 0:
        print("Aborting due to local changes.   Run 'git status' for details.", file=sys.stderr)
        return

    # Load .crispycookie.json
    with open(config_file) as fp:
        config = json.load(fp)

    # git worktree add TEMPLATE_UPDATE cookiecutter
    with use_git_worktree(project_dir, "TEMPLATE_UPDATE", branch) as workdir:
        print("Cleaning up existing content")
        # git ls-files | xargs rm
        stdout = run([GIT_BIN, "ls-files"], stdout=PIPE, check=True).stdout
        for file_name in stdout.splitlines():
            os.unlink(file_name)

        # Remove empty directories
        for (dirpath, dirnames, filenames) in os.walk(".", topdown=False):
            if ".git" in dirpath:
                continue
            if not dirnames and not filenames:
                os.rmdir(dirpath)

        # XXX: Check to see if crispycookie.json has changed 'git status --porcelain .crispycookie.json (and update commit message accordingly)
        # Show git diff of .crispycookie.json?   (In which case, writing to disk would be helpful)

        build_project(template_collection, workdir, config, verbose=verbose,
                      overwrite=True)

        print("Git add")
        # git add . && pre-commit run --all || git add .
        run([GIT_BIN, "add", "--all", "."], check=True)

        loop_limit = 3
        while loop_limit:
            print("Pre-running pre-commit")
            rc = run(["pre-commit", "run", "--all"], timeout=30).returncode
            print(f"Completed pre-commit with rc={rc}")
            if rc == 0:
                break
            print("Git add")
            run([GIT_BIN, "add", "--all", "."], check=True)
            loop_limit -= 1
        if not loop_limit:
            print("Unable to get pre-commit job to finish successfully after multiple attempts")
            return

        # git status (uses terminal stdout; for user feedback)
        run([GIT_BIN, "status"])

        status = git_status(".")
        if status["changed"]:
            repo_short = template_collection.short_repo
            rev = template_collection.rev

            print("Commiting....")
            # git commit -am "Update to cypress-cookiecutter@vX.Y.Z"
            # Disabling an hooks via --no-verify because any pre-commit work should have been done already by this point.
            run([GIT_BIN, "commit", "--no-verify",
                 "-m", f"Update to {repo_short}@{rev}"], check=True)
            if remote_ops:
                # git push
                print("git push")
                run([GIT_BIN, "push"], check=True)
                print("Project update completed:  Changes pushed to remote")
            else:
                print("Project update completed:  Changes committed locally.")
            print(f"Apply changes by running:    git merge {branch}")
        else:
            print("Project update completed:  No changes needed")
