
import logging
from pathlib import Path

log = logging.getLogger(__name__)

class GitManager:

    def __init__(self, runner, build_dir):
        self.runner = runner
        self.build_dir = Path(build_dir)

    def clone_and_update(self, url, project, branch="master", commit=None):
        repo = self.build_dir / project
        if not repo.is_dir():
            self.runner.run(["git", "clone", url, project], cwd=self.build_dir)

        self.runner.run(["git", "stash"], cwd=repo, check=False)
        self.runner.run(["git", "stash", "drop"], cwd=repo, check=False)
        self.runner.run(["git", "fetch"], cwd=repo, check=False)

        if commit:
            self.runner.run(["git", "checkout", commit], cwd=repo)
        else:
            self.runner.run(["git", "pull"], cwd=repo, check=False)
            self.runner.run(["git", "checkout", branch], cwd=repo)

        if not self.runner.dry_run:
            for gm in repo.rglob(".gitmodules"):
                text = gm.read_text()
                new_text = text.replace("git://", "https://").replace(
                    "ohwr.org/", "gitlab.com/ohwr/"
                )
                if new_text != text:
                    gm.write_text(new_text)
                    log.debug("Fixed submodule URLs in %s", gm)

        self.runner.run(["git", "submodule", "update", "--init"], cwd=repo, check=False)
        return repo

    def reset_submodules(self, repo):
        self.runner.run(
            ["git", "submodule", "foreach", "git checkout -- . 2>/dev/null || true"],
            cwd=repo,
            check=False,
        )

    def reset_working_tree(self, repo):
        self.runner.run(["git", "checkout", "--", "."], cwd=repo, check=False)

class PatchManager:

    def __init__(self, runner, config):
        self.runner = runner
        self.config = config

    def apply(self, project, repo, patch_name=None):
        if self.config.skip_patch:
            log.info("  Patching globally skipped")
            return

        comp = self.config.get_component(project)
        if comp.get("skip_patch", False):
            log.info("  Patching skipped for %s", project)
            return

        fname = patch_name or project
        patch_file = self.config.patch_dir / f"{fname}.diff"
        if not patch_file.is_file():
            log.debug("  No patch file: %s", patch_file)
            return

        log.info("  Applying patch: %s", patch_file.name)
        self.runner.run(
            ["patch", "-p1", "-i", str(patch_file)],
            cwd=repo,
        )

