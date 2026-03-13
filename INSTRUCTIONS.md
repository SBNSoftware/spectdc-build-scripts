# SPEC-TDC Build and Install Instructions

## Prerequisites

### System Requirements

- Linux kernel **5.14** (or compatible)
- Kernel headers installed for the running kernel:
  ```bash
  ls /lib/modules/$(uname -r)/build
  ```
- Git, GCC, Make, patch:
  ```bash
  sudo dnf install git gcc make patch
  ```
- Python 3 with PyYAML:
  ```bash
  pip3 install pyyaml
  # or: sudo dnf install python3-pyyaml
  ```
- Lua 5.1 (required by wishbone-gen):
  ```bash
  sudo dnf install lua
  ```
- Network access to `gitlab.cern.ch` and `gitlab.com` for cloning OHWR repositories

### Privilege Escalation

Installation steps require root. The build system uses `ksu`. Passwordless `ksu` must be configured for your user before running a build:

```bash
# Verify passwordless ksu works:
ksu -q -e /bin/true
echo $?   # must be 0
```

If `ksu` is not available or you prefer `sudo`, edit `config.yaml`:
```yaml
privilege_cmd: sudo   # or: null to disable install steps entirely
```

### Module Signing Certificates

On systems where the kernel enforces module signing, the `certs/signing_key.pem` and `certs/signing_key.x509` files must exist in the kernel headers tree. If they are missing, the build will fail when signing modules. Use the `--create-empty-certs` flag to create placeholder files:

```bash
python3 build.py --fresh --create-empty-certs
```

---

## Configuration

All settings are in `config.yaml` in the repository root. Key settings:

| Setting | Default | Description |
|---|---|---|
| `build_dir` | `/home/artdaq/spectdc/BUILD_DIR` | Directory where sources are cloned and built |
| `kversion` | `null` (auto-detect) | Override kernel version string |
| `linux_headers` | `null` (auto-detect) | Override path to kernel headers |
| `privilege_cmd` | `ksu` | Privilege escalation: `ksu`, `sudo`, or `null` |
| `skip.install` | `false` | Set to `true` to build without installing |

---

## Building and Installing

### Standard Fresh Build (recommended)

Clones all upstream sources from scratch, applies patches, builds, and installs:

```bash
cd /home/artdaq/spectdc/spectdc-build-scripts
python3 build.py --fresh
```

This will:
1. Remove existing source directories in `BUILD_DIR`
2. Clean build markers and staging directory
3. Check system dependencies (executables, Python modules, kernel headers, privilege escalation)
4. Unload and uninstall any previously installed modules and tools
5. Clone each component at its pinned commit
6. Apply compatibility patches (kernel 5.14)
7. Build all kernel modules and userspace tools
8. Stage artifacts to `BUILD_DIR/staging/`
9. Deploy kernel modules to `/lib/modules/<kversion>/extra/`
10. Deploy tools to `/usr/local/bin/`
11. Deploy helper scripts to `/lib/modules/<kversion>/extra/`
12. Run `depmod -a`

### Incremental Build

Preserves existing build markers and skips re-cloning and patching. Only rebuilds components that do not have a build marker (`tmp/built.<component>`):

```bash
python3 build.py --no-fresh
```

> **Note:** Any source files modified directly in `BUILD_DIR` will be discarded when a component is rebuilt. The `clone_and_update` step stashes and drops local changes before checking out the pinned commit. For fmc-tdc, its submodules (zio, fmc-bus) are also reset to clean state before building. Always apply modifications as patch files in the `patches/` directory instead.

### Build Without Installing

```bash
python3 build.py --fresh --skip-install
```

Artifacts will be staged to `BUILD_DIR/staging/` but not copied to system directories.

### Dry Run

Preview all commands that would be executed without running them:

```bash
python3 build.py --fresh --dry-run
```

---

## Loading Kernel Modules

After a successful build and install, load the SPEC and FMC-TDC modules:

```bash
python3 build.py --load-modules
```

This performs the following steps:
1. Unloads `fmc_tdc` and `spec` if currently loaded
2. Loads `spec` via `modprobe`
3. Loads `fmc-tdc` via `modprobe` with the TDC gateware bitstream:
   `gateware=fmc/wr_spec_tdc_17012017_rc2.bin`
4. Runs `update-permissions.sh` to set device file permissions for non-root access
5. Reports the loaded status of each module

> **Note:** Build markers for `spec` and `fmc-tdc` must exist (i.e., a build+install must have completed successfully) before `--load-modules` can run.

### Manual Module Loading

If needed, modules can be loaded manually:

```bash
ksu -q -e /usr/sbin/modprobe spec
ksu -q -e /usr/sbin/modprobe fmc-tdc gateware=fmc/wr_spec_tdc_17012017_rc2.bin
ksu -q -e /lib/modules/$(uname -r)/extra/update-permissions.sh
```

---

## Verifying the Installation

### Show Installed Components

```bash
python3 build.py --show-installed
```

Displays a table of all kernel modules and tools, their installation status, version strings (from `modinfo`), and current build markers.

### Check for Symbol Errors

```bash
python3 build.py --show-depmod-report
```

Runs `depmod -nae` against the installed modules and reports any unresolved symbol warnings or errors per module.

### Check Loaded Modules

```bash
lsmod | grep -E 'spec|fmc|zio'
```

Expected output after successful module load:

```
fmc_tdc        ...
spec           ...
zio            ...
fmc            ...
fpga_mgr       ...
```

### Verify ZIO Devices

After loading, the TDC device should appear in sysfs:

```bash
ls /sys/bus/zio/devices/
# Expected: tdc-1n5c-<id> entries
```

---

## Running Tests

A basic smoke test script enables termination on all 5 channels, reads temperature, synchronises time to White Rabbit, and collects timestamps for 5 seconds:

```bash
/lib/modules/$(uname -r)/extra/run-tests.sh
```

> Must be run as a non-root user. Requires the modules to be loaded and `update-permissions.sh` to have been run first.

---

## Uninstalling

Unload modules and remove all installed files (modules and tools):

```bash
python3 build.py --uninstall
```

This will:
1. Unload all SPEC-TDC kernel modules in safe dependency order
2. Delete all installed `.ko` files from `/lib/modules/<kversion>/extra/`
3. Delete all installed tools from `/usr/local/bin/`
4. Run `depmod -a`
5. Clear build markers
