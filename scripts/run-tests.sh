#!/usr/bin/bash

(( $(id -u) != 0 )) || { echo "do not run as root" ; exit 1; }

tdc_sys=(/sys/bus/zio/devices/tdc-1n5c-[0-9]*)
if [[ ! -d ${tdc_sys[0]} ]]; then
    echo "No FMC-TDC device found in /sys/bus/zio/devices/" >&2
    exit 1
fi
tdcdev=${tdc_sys[0]##*/tdc-1n5c-}
echo "Using TDC device: $tdcdev"

fmc-tdc-term $tdcdev 0 on
fmc-tdc-term $tdcdev 1 on
fmc-tdc-term $tdcdev 2 on
fmc-tdc-term $tdcdev 3 on
fmc-tdc-term $tdcdev 4 on

fmc-tdc-temperature $tdcdev
fmc-tdc-time $tdcdev get
fmc-tdc-time $tdcdev wr
fmc-tdc-tstamp 0x${tdcdev} -s 5

