#!/usr/bin/bash

(( $(id -u) == 0 )) ||  { echo "run as root" ; exit -1; }

ziodevdir=/sys/bus/zio/devices
tdcdevs=tdc-1n5c-*
chmod a+r /dev/zio/${tdcdevs}
chmod a+w ${ziodevdir}/${tdcdevs}/command
chmod a+w ${ziodevdir}/hw-${tdcdevs}/${tdcdevs}/ft-ch*/diff-reference
chmod a+w ${ziodevdir}/${tdcdevs}/ft-ch*/trigger/post-samples
chmod a+w ${ziodevdir}/${tdcdevs}/ft-ch*/{enable,termination,user-offset}
chmod a+w ${ziodevdir}/${tdcdevs}/ft-ch*/chan*/buffer/flush
chmod a+rw ${ziodevdir}/${tdcdevs}/ft-ch*/chan*/buffer/{prefer-new,uevent,max-buffer-len}
chmod a+rw ${ziodevdir}/${tdcdevs}/ft-ch*/chan*/buffer/power/{async,autosuspend_delay_ms} 2>/dev/null || true

