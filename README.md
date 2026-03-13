# SPEC-TDC Build Scripts

## Overview

The SPEC-TDC is a Time-to-Digital Converter (TDC) board mounted on a SPEC (Simple PCIe FMC Carrier) PCIe carrier. It provides sub-nanosecond timestamping for up to 5 input channels and is used in the SBND detector's data acquisition system.

This repository provides a `build.py` script that automates cloning, patching, building, staging, and installing all required kernel modules and userspace tools from source.

## What Gets Built

The `build.py` script builds the following components in dependency order:

| Component | Description |
|---|---|
| `cheby` | Register map generator (Python tool, build-time dependency) |
| `wishbone-gen` | Wishbone register generator (build-time dependency) |
| `fpga-manager` | FPGA firmware loader kernel module |
| `general-cores` | OHWR I2C, SPI, and HTVIC interrupt controller kernel modules |
| `spec` | SPEC PCIe carrier kernel driver (`spec.ko`) |
| `fmc-tdc` | FMC-TDC kernel driver, FMC bus modules, and userspace tools |
| `zio-tdc` | ZIO framework kernel modules (built from fmc-tdc's bundled submodule) |

### Installed Kernel Modules

- **fpga-manager**: `fpga-mgr.ko`
- **general-cores**: `htvic.ko`, `i2c-ocores.ko`, `spi-ocores.ko`
- **SPEC carrier**: `spec.ko`
- **FMC bus**: `fmc.ko`, `fmc-chardev.ko`, `fmc-fakedev.ko`, `fmc-trivial.ko`, `fmc-write-eeprom.ko`
- **FMC-TDC**: `fmc-tdc.ko`
- **ZIO framework**: `zio.ko`, `zio-buf-vmalloc.ko`, `zio-trig-hrt.ko`, `zio-trig-irq.ko`, `zio-trig-timer.ko`, `zio-ad788x.ko`, `zio-fake-dtc.ko`, `zio-gpio.ko`, `zio-irq-tdc.ko`, `zio-loop.ko`, `zio-mini.ko`, `zio-vmk8055.ko`, `zio-zero.ko`

### Installed Userspace Tools

`fmc-tdc-list`, `fmc-tdc-term`, `fmc-tdc-temperature`, `fmc-tdc-time`, `fmc-tdc-tstamp`, `fmc-tdc-offset`

Installation steps (copying modules to `/lib/modules/`, running `depmod`) require root. The system is configured to use `ksu` for privilege escalation. Passwordless `ksu` access must be configured before running a build with installation enabled.

## Quick Start

```bash
cd spectdc-build-scripts
python3 build.py --fresh
```

See [INSTRUCTIONS.md](INSTRUCTIONS.md) for full prerequisites and detailed usage.
