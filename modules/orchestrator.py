
import argparse
import datetime
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from modules.log_setup import setup_logging
from modules.config import BuildConfig
from modules.runner import BuildEnvironment, CommandRunner, DependencyChecker
from modules.scm import GitManager, PatchManager
from modules.components import COMPONENT_CLASSES

log = logging.getLogger(__name__)

class BuildOrchestrator:

    def __init__(self, config, dry_run=False, fresh=False, no_fresh=False,
                 create_empty_certs=False):
        self.config = config
        self.dry_run = dry_run
        self.fresh = fresh
        self.no_fresh = no_fresh
        self.create_empty_certs = create_empty_certs
        self.markers_cleaned = False
        self.build_env = BuildEnvironment(config)
        self.runner = CommandRunner(self.build_env, dry_run=dry_run)
        self.git = GitManager(self.runner, config.build_dir)
        self.patcher = PatchManager(self.runner, config)

        self.components = {}
        for name, cls in COMPONENT_CLASSES.items():
            if name in config.components:
                self.components[name] = cls(
                    config, self.build_env, self.runner, self.git, self.patcher
                )

    def _topological_sort(self):
        in_degree = {}
        graph = {}
        for name in self.components:
            comp_cfg = self.config.components[name]
            deps = comp_cfg.get("depends_on", [])
            in_degree.setdefault(name, 0)
            graph.setdefault(name, [])
            for dep in deps:
                graph.setdefault(dep, [])
                graph[dep].append(name)
                in_degree[name] = in_degree.get(name, 0) + 1

        queue = sorted([n for n in in_degree if in_degree[n] == 0])
        order = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in sorted(graph.get(node, [])):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self.components):
            built = set(order)
            missing = set(self.components) - built
            undefined = set()
            for name in missing:
                for dep in self.config.components[name].get("depends_on", []):
                    if dep not in self.components:
                        undefined.add(dep)
            if undefined:
                log.critical("Undefined dependencies: %s", undefined)
            else:
                log.critical("Circular dependency among: %s", missing)
            sys.exit(1)

        return order

    def clean_sources(self):
        for name in self.components:
            comp_cfg = self.config.components[name]
            if not comp_cfg.get("enabled", True):
                log.info("  Skipping %s (disabled)", name)
                continue
            if comp_cfg.get("source_override"):
                log.info("  Skipping %s (uses source_override)", name)
                continue
            src_dir = self.config.build_dir / name
            if src_dir.is_dir():
                log.info("  Removing %s", src_dir)
                if not self.dry_run:
                    shutil.rmtree(src_dir)
            else:
                log.debug("  %s does not exist — nothing to remove", src_dir)

    def clean_staging(self):
        staging = self.config.staging_dir
        if staging.is_dir():
            log.info("  Removing staging directory: %s", staging)
            if not self.dry_run:
                shutil.rmtree(staging)

    def clean_markers(self):
        for marker in self.config.marker_dir.glob("built.*"):
            log.debug("  Removing marker: %s", marker.name)
            if not self.dry_run:
                marker.unlink()

        deps_ok = self.config.marker_dir / "deps.ok"
        if deps_ok.is_file():
            log.debug("  Removing deps.ok")
            if not self.dry_run:
                deps_ok.unlink()

        self.markers_cleaned = True

    def deploy(self):
        log.info("Deploying staged artifacts to system")
        staging = self.config.staging_dir
        kversion = self.config.kversion
        system_extra = Path(f"/lib/modules/{kversion}/extra")

        staged_extra = staging / "lib" / "modules" / kversion / "extra"
        if staged_extra.is_dir():
            self.runner.privileged_run(["/usr/bin/mkdir", "-p", str(system_extra)])
            self.runner.privileged_run(
                ["/usr/bin/cp", "-a", str(staged_extra) + "/.", str(system_extra)])

        staged_tools = staging / "usr" / "local" / "bin"
        system_tools = Path("/usr/local/bin")
        if staged_tools.is_dir():
            self.runner.privileged_run(["/usr/bin/mkdir", "-p", str(system_tools)])
            self.runner.privileged_run(
                ["/usr/bin/cp", "-a", str(staged_tools) + "/.", str(system_tools)])

        scripts_dir = self.config._path.parent / "scripts"
        sh_files = sorted(scripts_dir.glob("*.sh"))
        if sh_files:
            log.info("Copying %d script(s) from %s to %s", len(sh_files), scripts_dir, system_extra)
            self.runner.privileged_run(["/usr/bin/mkdir", "-p", str(system_extra)])
            for sh in sh_files:
                self.runner.privileged_run(["/usr/bin/cp", str(sh), str(system_extra / sh.name)])
            self.runner.privileged_run(
                ["/usr/bin/chmod", "a+rx"] + [str(system_extra / sh.name) for sh in sh_files])
        else:
            log.debug("No .sh files found in %s — skipping script deployment", scripts_dir)

        self.runner.privileged_run(
            ["/usr/sbin/depmod", "-a", kversion], check=False)

    def _is_built(self, comp):
        if self.markers_cleaned and self.dry_run:
            return False
        return comp.is_built()

    @staticmethod
    def _modinfo_version(ko_path):
        try:
            result = subprocess.run(
                ["modinfo", "-F", "version", str(ko_path)],
                capture_output=True, text=True, timeout=5,
            )
            ver = result.stdout.strip()
            return ver if ver else "-"
        except (OSError, subprocess.TimeoutExpired):
            return "-"

    def _find_installed_modules(self, extra_dir):
        installed = {}
        try:
            for p in extra_dir.rglob("*.ko"):
                installed[p.name] = p
            if installed:
                return installed
        except PermissionError:
            pass

        prefix = self.build_env.privilege_prefix()
        if not prefix:
            return installed
        cmd = prefix + ["/usr/bin/find", str(extra_dir), "-name", "*.ko"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=False)
            for line in result.stdout.strip().splitlines():
                p = Path(line.strip())
                installed[p.name] = p
        except Exception as exc:
            log.debug("  Privileged module scan failed: %s", exc)
        return installed

    def show_installed(self):
        kversion = self.config.kversion
        extra_dir = Path(f"/lib/modules/{kversion}/extra")
        tools_dir = Path("/usr/local/bin")
        order = self._topological_sort()

        log.info("=" * 60)
        log.info("  Installed SPEC-TDC components (kversion: %s)", kversion)
        log.info("=" * 60)

        log.info("")
        log.info("Kernel modules (%s):", extra_dir)
        log.info("")
        hdr = "  %-28s %-16s %-30s %s" % ("Module", "Component", "Version", "Status")
        log.info("%s", hdr)
        log.info("  %s", "-" * (len(hdr) - 2))

        installed_modules = self._find_installed_modules(extra_dir)

        seen_modules = set()
        has_modules = False
        for name in order:
            comp = self.components[name]
            for ko in comp.installed_modules:
                if ko in seen_modules:
                    continue
                seen_modules.add(ko)
                has_modules = True
                installed_path = installed_modules.get(ko)
                if installed_path:
                    version = self._modinfo_version(installed_path)
                    status = "installed"
                else:
                    built_paths = list(
                        self.config.build_dir.rglob(ko)
                    )
                    if built_paths:
                        version = self._modinfo_version(built_paths[0])
                        status = "built (not installed)"
                    else:
                        version = "-"
                        status = "not found"
                log.info("  %-28s %-16s %-30s %s", ko, name, version, status)

        if not has_modules:
            log.info("  (none)")

        log.info("")
        log.info("Tools (%s):", tools_dir)
        log.info("")
        hdr = "  %-28s %-16s %s" % ("Program", "Component", "Status")
        log.info("%s", hdr)
        log.info("  %s", "-" * (len(hdr) - 2))

        has_tools = False
        for name in order:
            comp = self.components[name]
            for tool in comp.installed_tools:
                has_tools = True
                installed_path = tools_dir / tool
                if installed_path.is_file():
                    status = "installed"
                else:
                    built_paths = list(
                        self.config.build_dir.rglob(tool)
                    )
                    built_paths = [p for p in built_paths if p.is_file()
                                   and not p.suffix]
                    if built_paths:
                        status = "built (not installed)"
                    else:
                        status = "not found"
                log.info("  %-28s %-16s %s", tool, name, status)

        if not has_tools:
            log.info("  (none)")

        log.info("")
        log.info("Build markers (%s):", self.config.marker_dir)
        markers = sorted(self.config.marker_dir.glob("built.*"))
        if markers:
            for m in markers:
                comp_name = m.name.removeprefix("built.")
                log.info("  %s", comp_name)
        else:
            log.info("  (none)")

        log.info("")
        log.info("=" * 60)

    def show_depmod_report(self):
        kversion = self.config.kversion
        extra_dir = Path(f"/lib/modules/{kversion}/extra")
        order = self._topological_sort()

        log.info("=" * 60)
        log.info("  depmod report (kversion: %s)", kversion)
        log.info("=" * 60)

        system_map = Path(f"/boot/System.map-{kversion}")
        if system_map.is_file():
            depmod_cmd = ["/usr/sbin/depmod", "-nae", "-F", str(system_map), kversion]
        else:
            log.warning("  System.map not found at %s — symbol checks skipped", system_map)
            depmod_cmd = ["/usr/sbin/depmod", "-na", kversion]

        result = None
        for cmd in [depmod_cmd,
                    self.build_env.privilege_prefix() + depmod_cmd
                    if self.build_env.privilege_prefix() else None]:
            if cmd is None:
                continue
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30,
                )
                break
            except PermissionError:
                continue
            except (OSError, subprocess.TimeoutExpired) as exc:
                log.error("  Failed to run depmod: %s", exc)
                return

        if result is None:
            log.error("  Could not run depmod (no privilege escalation available)")
            return

        raw_output = result.stderr + result.stdout

        module_messages = {}
        general_messages = []

        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            if not re.search(r'\b(WARNING|ERROR)\b', line):
                continue
            ko_match = re.search(r'(/[^\s]+\.ko)', line)
            if ko_match:
                ko_name = Path(ko_match.group(1)).name
                module_messages.setdefault(ko_name, []).append(line)
            else:
                general_messages.append(line)

        installed_modules = self._find_installed_modules(extra_dir)
        seen = set()
        any_errors = False

        log.info("")
        hdr = "  %-28s %-16s %s" % ("Module", "Component", "Result")
        log.info("%s", hdr)
        log.info("  %s", "-" * (len(hdr) - 2))

        for name in order:
            comp = self.components[name]
            for ko in comp.installed_modules:
                if ko in seen:
                    continue
                seen.add(ko)

                if ko not in installed_modules:
                    log.info("  %-28s %-16s %s", ko, name, "not installed")
                    continue

                msgs = module_messages.get(ko, [])
                if msgs:
                    any_errors = True
                    log.warning("  %-28s %-16s ERRORS (%d)", ko, name, len(msgs))
                    for msg in msgs:
                        log.warning("      %s", msg)
                else:
                    log.info("  %-28s %-16s OK", ko, name)

        if general_messages:
            any_errors = True
            log.info("")
            log.info("  General depmod warnings:")
            for msg in general_messages:
                log.warning("      %s", msg)

        log.info("")
        log.info("=" * 60)
        if any_errors:
            log.warning("  depmod check: ERRORS found (see above)")
        else:
            log.info("  depmod check: all modules OK")
        log.info("=" * 60)

    def _get_loaded_modules(self):
        loaded = {}
        try:
            with open("/proc/modules") as f:
                for line in f:
                    parts = line.split()
                    name = parts[0]
                    used_by_str = parts[3] if len(parts) > 3 else "-"
                    if used_by_str == "-":
                        used_by = []
                    else:
                        used_by = [m for m in used_by_str.rstrip(",").split(",") if m]
                    loaded[name] = used_by
        except OSError:
            pass
        return loaded

    def _unload_modules(self, order):
        log.info("Unloading kernel modules")

        our_modules = set()
        for name in order:
            if not self.config.components[name].get("enabled", True):
                continue
            comp = self.components[name]
            for ko in comp.installed_modules:
                our_modules.add(ko.removesuffix(".ko").replace("-", "_"))
            for mod_name in comp.cleanup_modules:
                our_modules.add(mod_name)

        if self.dry_run:
            unload_order = self._compute_unload_order(our_modules)
            for mod_name in unload_order:
                self.runner.privileged_run(["/usr/sbin/rmmod", mod_name], check=False)
            return

        loaded = self._get_loaded_modules()

        to_unload = sorted(our_modules & set(loaded.keys()))
        if not to_unload:
            log.info("  No SPEC-TDC modules currently loaded")
            return

        dependents = {m: [] for m in to_unload}
        for mod in to_unload:
            for user in loaded.get(mod, []):
                if user in to_unload:
                    dependents[mod].append(user)

        unloaded = set()
        unload_order = []
        remaining = set(to_unload)

        while remaining:
            ready = [m for m in remaining
                     if all(d in unloaded for d in dependents[m])]
            if not ready:
                log.warning("  Cannot safely unload (in use): %s",
                            ", ".join(sorted(remaining)))
                break
            for mod in sorted(ready):
                remaining.discard(mod)
                unloaded.add(mod)
                unload_order.append(mod)

        for mod_name in unload_order:
            self.runner.privileged_run(["/usr/sbin/rmmod", mod_name], check=False)

    def _compute_unload_order(self, our_modules):
        deps = {}
        for mod in our_modules:
            deps[mod] = set()
            ko_name = mod.replace("_", "-") + ".ko"
            for ko_path in self.config.build_dir.rglob(ko_name):
                try:
                    result = subprocess.run(
                        ["modinfo", "-F", "depends", str(ko_path)],
                        capture_output=True, text=True, timeout=5,
                    )
                    for dep in result.stdout.strip().split(","):
                        dep = dep.strip()
                        if dep and dep in our_modules:
                            deps[mod].add(dep)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                break

        dependents = {m: [] for m in our_modules}
        for mod, mod_deps in deps.items():
            for dep in mod_deps:
                if dep in dependents:
                    dependents[dep].append(mod)

        unloaded = set()
        unload_order = []
        remaining = set(our_modules)

        while remaining:
            ready = [m for m in remaining
                     if all(d in unloaded for d in dependents[m])]
            if not ready:
                unload_order.extend(sorted(remaining))
                break
            for mod in sorted(ready):
                remaining.discard(mod)
                unloaded.add(mod)
                unload_order.append(mod)

        return unload_order

    def load_modules(self):
        kversion = self.config.kversion

        spec_marker = self.config.marker_dir / "built.spec"
        tdc_marker = self.config.marker_dir / "built.fmc-tdc"
        if not spec_marker.exists() or not tdc_marker.exists():
            log.error(
                "Build markers for 'spec' and/or 'fmc-tdc' not found in %s. "
                "Run a successful build (with install enabled) first.",
                self.config.marker_dir,
            )
            sys.exit(1)

        log.info("=" * 60)
        log.info("  Loading SPEC-TDC kernel modules")
        log.info("=" * 60)

        gateware = "fmc/wr_spec_tdc_17012017_rc2.bin"
        permissions_script = f"/lib/modules/{kversion}/extra/update-permissions.sh"

        log.info("Unloading fmc-tdc module")
        self.runner.privileged_run(["/usr/sbin/rmmod", "fmc_tdc"], check=False)

        log.info("Unloading spec module")
        self.runner.privileged_run(["/usr/sbin/rmmod", "spec"], check=False)

        log.info("Loading spec module")
        self.runner.privileged_run(["/usr/sbin/modprobe", "spec"])

        log.info("Loading fmc-tdc module (gateware=%s)", gateware)
        self.runner.privileged_run([
            "/usr/sbin/modprobe", "fmc-tdc",
            f"gateware={gateware}",
        ])

        log.info("Running update-permissions.sh")
        self.runner.privileged_run([permissions_script])

        log.info("")
        log.info("Checking loaded modules")

        check_modules = [("spec", "spec"), ("fmc_tdc", "fmc-tdc")]

        if not self.dry_run:
            loaded = self._get_loaded_modules()
        else:
            loaded = {}

        all_ok = True
        hdr = "  %-32s %-16s %s" % ("Module", "Component", "Status")
        log.info("%s", hdr)
        log.info("  %s", "-" * (len(hdr) - 2))
        for mod_name, comp_name in check_modules:
            is_loaded = mod_name in loaded
            status = "loaded" if is_loaded else "NOT LOADED"
            if is_loaded:
                log.info("  %-32s %-16s %s", mod_name, comp_name, status)
            else:
                log.warning("  %-32s %-16s %s", mod_name, comp_name, status)
                all_ok = False

        log.info("")
        log.info("=" * 60)
        if self.dry_run:
            log.info("  [dry-run] Module load check skipped")
        elif all_ok:
            log.info("  All modules loaded successfully")
        else:
            log.warning("  Some modules are not loaded (see above)")
        log.info("=" * 60)

        if not self.dry_run and not all_ok:
            sys.exit(1)

    def uninstall(self):
        order = self._topological_sort()
        reverse_order = list(reversed(order))

        log.info("=" * 60)
        log.info("  SPEC-TDC Uninstall")
        log.info("=" * 60)
        log.info("Uninstall order: %s", " -> ".join(reverse_order))

        log.info("")
        self._unload_modules(reverse_order)

        failed = []
        for name in reverse_order:
            if not self.config.components[name].get("enabled", True):
                continue
            comp = self.components[name]
            log.info("")
            log.info("  Uninstalling: %s", name)
            try:
                comp.uninstall()
            except (subprocess.CalledProcessError, OSError) as exc:
                log.warning("  Uninstall step failed for %s — %s (continuing)", name, exc)
                failed.append(name)

        log.info("")
        log.info("Running depmod")
        self.runner.privileged_run(
            ["/usr/sbin/depmod", "-a", self.config.kversion], check=False,
        )

        log.info("Cleaning build markers")
        self.clean_markers()

        log.info("")
        log.info("=" * 60)
        if failed:
            log.warning("  Uninstall completed with warnings: %s", ", ".join(failed))
        else:
            log.info("  Uninstall complete")
        log.info("=" * 60)

    def ensure_empty_certs(self):
        certs_dir = self.config.linux_headers / "certs"
        pem = certs_dir / "signing_key.pem"
        x509 = certs_dir / "signing_key.x509"

        if pem.is_file() and x509.is_file() and os.access(pem, os.R_OK) and os.access(x509, os.R_OK):
            log.info("Module signing certs already exist and are readable — skipping")
            return

        log.info("Creating empty module signing certificates in %s", certs_dir)
        self.runner.privileged_run(
            ["/usr/bin/mkdir", "-p", str(certs_dir)])
        if not pem.is_file():
            self.runner.privileged_run(
                ["/usr/bin/touch", str(pem)])
        if not x509.is_file():
            self.runner.privileged_run(
                ["/usr/bin/touch", str(x509)])
        self.runner.privileged_run(
            ["/usr/bin/chmod", "644", str(pem), str(x509)])

    def run(self):
        start_time = datetime.datetime.now()
        log.info("=" * 60)
        log.info("  SPEC-TDC Build")
        log.info("  build_dir: %s", self.config.build_dir)
        log.info("  kversion:  %s", self.config.kversion)
        log.info("  linux:     %s", self.config.linux_headers)
        log.info("=" * 60)

        self.config.build_dir.mkdir(parents=True, exist_ok=True)
        (self.config.build_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.config.marker_dir.mkdir(parents=True, exist_ok=True)
        if not self.config.skip_install:
            self.config.staging_dir.mkdir(parents=True, exist_ok=True)

        if self.fresh:
            log.info("Fresh build: removing source directories")
            self.clean_sources()

        if self.no_fresh:
            log.info("Incremental build: keeping existing markers and patches")
        else:
            log.info("Cleaning build markers and staging")
            self.clean_markers()
            self.clean_staging()

        log.info("Checking dependencies")
        checker = DependencyChecker(self.config)
        checker.check_all()

        if self.create_empty_certs:
            self.ensure_empty_certs()

        order = self._topological_sort()
        log.info("Build order: %s", " -> ".join(order))

        if self.no_fresh:
            self.config.skip_patch = True

        if not self.config.skip_install:
            log.info("")
            log.info("Uninstalling previous installation before rebuilding")
            self._unload_modules(list(reversed(order)))
            for name in reversed(order):
                if not self.config.components[name].get("enabled", True):
                    continue
                comp = self.components[name]
                try:
                    comp.uninstall()
                except (subprocess.CalledProcessError, OSError) as exc:
                    log.warning("  Pre-build uninstall of %s skipped — %s", name, exc)

        failed = []
        for name in order:
            comp = self.components[name]
            comp_cfg = self.config.components[name]
            if not comp_cfg.get("enabled", True):
                log.info("  %s disabled — skipping", name)
                comp.apply_exports()
                continue
            if self._is_built(comp):
                log.info("  %s already built — skipping", name)
                comp.apply_exports()
                continue

            log.info("")
            log.info("=" * 60)
            log.info("  Building: %s", name)
            log.info("=" * 60)
            try:
                comp.build()
            except (subprocess.CalledProcessError, OSError) as exc:
                log.error("  FAILED: %s — %s", name, exc)
                failed.append(name)
                break

        if not failed and not self.config.skip_install:
            log.info("")
            self.deploy()

        elapsed = datetime.datetime.now() - start_time
        log.info("")
        log.info("=" * 60)
        if failed:
            log.error("  Build FAILED at: %s", ", ".join(failed))
            log.info("  Elapsed: %s", elapsed)
            log.info("=" * 60)
            sys.exit(1)
        else:
            log.info("  All components built successfully")
            log.info("  Elapsed: %s", elapsed)
            log.info("=" * 60)

def main():
    parser = argparse.ArgumentParser(
        description="Build orchestrator for OHWR SPEC-TDC projects"
    )
    parser.add_argument(
        "-c", "--config",
        default=str(Path(__file__).resolve().parent.parent / "config.yaml"),
        help="Path to config.yaml (default: config.yaml next to this script)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing commands",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete component source directories and re-clone from scratch",
    )
    parser.add_argument(
        "--no-fresh",
        action="store_true",
        dest="no_fresh",
        help="Incremental build: skip patching and only rebuild components "
             "that were not previously built",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        dest="skip_install",
        help="Skip install steps (overrides config.yaml skip.install setting)",
    )
    parser.add_argument(
        "--show-installed",
        action="store_true",
        dest="show_installed",
        help="Show installed kernel modules, tools, and build markers",
    )
    parser.add_argument(
        "--show-depmod-report",
        action="store_true",
        dest="show_depmod_report",
        help="Run depmod -nae and report any unresolved symbol errors per module",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall all installed components (reverse dependency order)",
    )
    parser.add_argument(
        "--load-modules",
        action="store_true",
        dest="load_modules",
        help="Reload spec and fmc-tdc kernel modules after a successful deployment",
    )
    parser.add_argument(
        "--create-empty-certs",
        action="store_true",
        dest="create_empty_certs",
        help="Create empty module signing certificates if missing (suppresses "
             "sign-file errors on systems without a signing key)",
    )
    args = parser.parse_args()

    if args.fresh and args.no_fresh:
        parser.error("--fresh and --no-fresh are mutually exclusive")

    if args.show_installed and args.uninstall:
        parser.error("--show-installed and --uninstall cannot be used together")

    report_flags = sum([
        args.show_installed, args.show_depmod_report,
        args.uninstall, args.load_modules,
    ])
    if report_flags > 1:
        parser.error("--show-installed, --show-depmod-report, --uninstall, and "
                     "--load-modules are mutually exclusive")

    config = BuildConfig(args.config)

    if args.skip_install:
        config.skip_install = True

    setup_logging(config.log_level, config.log_file, config.log_colored)

    orchestrator = BuildOrchestrator(config, dry_run=args.dry_run, fresh=args.fresh,
                                        no_fresh=args.no_fresh,
                                        create_empty_certs=args.create_empty_certs)

    if args.show_installed:
        orchestrator.show_installed()
    elif args.show_depmod_report:
        orchestrator.show_depmod_report()
    elif args.uninstall:
        orchestrator.uninstall()
    elif args.load_modules:
        orchestrator.load_modules()
    else:
        orchestrator.run()

