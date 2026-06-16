# -*- coding: utf-8 -*-
"""
Logic module for controlling an iBeam Smart laser as a CW repump source
within the PLE scan workflow.

Features:
  - CW on/off toggle
  - Power control (µW)
  - "Line repump": after each completed scan line the laser fires for a
    configurable duration before the next line is started.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.
"""

import time
from PySide2 import QtCore

from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.core.statusvariable import StatusVar

try:
    from toptica.lasersdk.dlcpro.v2_0_3 import DLCpro, NetworkConnection
except ImportError:
    pass

class IBeamScanMonitorThread(QtCore.QThread):
    def __init__(self, logic, lines, fit_config, scan_axes, caller_id):
        super().__init__()
        self.logic = logic
        self.lines = lines
        self.fit_config = fit_config
        self.scan_axes = scan_axes
        self.caller_id = caller_id
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        hw = self.logic._ibeam()
        scan = self.logic._scanning_logic()
        try:
            dlc_hw = self.logic._dl_pro()
        except:
            self.logic.log.error("DLC Pro connector missing. Cannot perform line repump active polling.")
            return

        try:
            with DLCpro(NetworkConnection(dlc_hw.tcp_address)) as dlc:
                # 1. Setup DLC pro for manual per-line triggering
                dlc.laser1.wide_scan.trigger.output_enabled.set(True)
                dlc.laser1.wide_scan.continuous_mode.set(False)

                # 2. Ensure baseline CW state
                if self.logic._cw_enabled:
                    hw.setPower(self.logic._power_uW)
                    hw.enable()
                else:
                    hw.disable()

                # 3. Start the qudi scan (configures timetagger and emits StartScanner)
                scan.toggle_scan(True, tuple(self.scan_axes), self.caller_id)
                time.sleep(1.0) # give qudi time to lock and start

                for current_line in range(self.lines):
                    if self._stop_flag or scan.module_state() != 'locked':
                        break

                    # Start hardware sweep
                    laser_state = dlc.laser1.wide_scan.state.get()
                    if laser_state == 0:
                        dlc.laser1.wide_scan.start()

                    time.sleep(0.5)

                    # Wait for sweep to finish
                    laser_state = dlc.laser1.wide_scan.state.get()
                    while laser_state != 0:
                        if self._stop_flag:
                            break
                        time.sleep(1)
                        laser_state = dlc.laser1.wide_scan.state.get()

                    time.sleep(1)

                    # Assess Repump conditions
                    do_repump_this_line = self.logic._line_repump_enabled

                    if self.logic._line_repump_enabled and self.logic._conditional_repump and not self._stop_flag:
                        channel = scan._channel
                        
                        if self.fit_config != "No Fit":
                            # Process the fit for the latest acquired line
                            scan.do_fit(self.fit_config, channel, averaged=False)
                            fit_res = scan.fit_results.get(channel)
                            
                            # None means the fit failed, implying defect is ionized
                            do_repump_this_line = (fit_res is None)
                        else:
                            do_repump_this_line = True
                            
                    # Apply the Repump pulse
                    if do_repump_this_line and not self._stop_flag:
                        try:
                            hw.setPower(self.logic._power_uW)
                            hw.enable()
                            time.sleep(self.logic._line_repump_duration)
                        finally:
                            if self.logic._cw_enabled:
                                hw.setPower(self.logic._power_uW)
                                hw.enable()
                            else:
                                hw.disable()

        except Exception as e:
            self.logic.log.exception("Error in active polling line repump loop:")

        self._stop_flag = False
        
        # Conclude scan if it hasn't stopped
        if scan.module_state() == 'locked':
            scan.toggle_scan(False, tuple(self.scan_axes), self.caller_id)


class IBeamRepumpLogic(LogicBase):
    """Logic that wraps an iBeam Smart laser for use as a CW/line repump
    source in PLE scans."""

    # ── connectors ────────────────────────────────────────────────────────────
    _ibeam = Connector(name='ibeam', interface='iBeamSmart')
    _dl_pro = Connector(name='dl_pro', interface='SimpleLaserInterface', optional=True)
    _scanning_logic = Connector(name='scanning_logic', interface='ScanningProbeLogic', optional=True)

    # ── status variables (persisted across sessions) ───────────────────────
    _power_uW = StatusVar(name='power_uW', default=1000.0)
    _cw_enabled = StatusVar(name='cw_enabled', default=False)
    _line_repump_enabled = StatusVar(name='line_repump_enabled', default=False)
    _line_repump_duration = StatusVar(name='line_repump_duration', default=0.5)
    _conditional_repump = StatusVar(name='conditional_repump', default=False)

    # ── signals ───────────────────────────────────────────────────────────────
    # Emitted whenever hardware state changes so the GUI can refresh.
    sigStateUpdated = QtCore.Signal(bool, float)   # (cw_enabled, power_uW)

    # ─────────────────────────────────────────────────────────────────────────

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._scan_thread = None

    def on_activate(self):
        """Restore hardware state from StatusVars."""
        hw = self._ibeam()
        hw.setPower(self._power_uW)
        if self._cw_enabled:
            hw.enable()
        else:
            hw.disable()
        self.sigStateUpdated.emit(self._cw_enabled, self._power_uW)

    def on_deactivate(self):
        """Make laser safe: disable it on deactivation."""
        try:
            self._ibeam().disable()
        except Exception:
            pass

    # ── CW control ───────────────────────────────────────────────────────────

    @QtCore.Slot(bool)
    def set_cw(self, enabled: bool):
        """Enable/disable the iBeam laser in CW mode.

        @param bool enabled: True → laser on, False → laser off
        """
        hw = self._ibeam()
        if enabled:
            hw.setPower(self._power_uW)
            hw.enable()
        else:
            hw.disable()
        self._cw_enabled = enabled
        self.sigStateUpdated.emit(self._cw_enabled, self._power_uW)

    @QtCore.Slot(float)
    def set_power(self, power_uW: float):
        """Set the laser output power.

        @param float power_uW: Target power in µW
        """
        self._power_uW = power_uW
        self._ibeam().setPower(power_uW)
        self.sigStateUpdated.emit(self._cw_enabled, self._power_uW)

    # ── line-repump control ───────────────────────────────────────────────────

    @QtCore.Slot(bool)
    def set_line_repump_enabled(self, enabled: bool):
        """Enable/disable the between-line repump feature.

        @param bool enabled: True → repump after every scan line
        """
        self._line_repump_enabled = enabled

    @QtCore.Slot(bool)
    def set_conditional_repump(self, enabled: bool):
        """Enable/disable conditional repump based on fit failing.
        """
        self._conditional_repump = enabled
        
    def run_custom_scan(self, lines: int, fit_config: str, scan_axes: list, caller_id):
        """Spawns background thread for active polling over the scan."""
        self.stop_custom_scan()
        self._scan_thread = IBeamScanMonitorThread(self, lines, fit_config, scan_axes, caller_id)
        self._scan_thread.start()

    def stop_custom_scan(self):
        """Stops the background active polling thread if running."""
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.stop()
            self._scan_thread.wait()
        self._scan_thread = None

    @QtCore.Slot(float)
    def set_line_repump_duration(self, duration_s: float):
        """Set the duration for which the laser fires between scan lines.

        @param float duration_s: Dwell time in seconds
        """
        self._line_repump_duration = duration_s

    @QtCore.Slot(bool, tuple)
    def do_line_repump(self, start: bool, scan_axes: tuple):
        """Slot connected to PLEScannerLogic.sigRepeatScan.

        Called between every scan line.  When *start* is True a new line is
        about to begin: if line_repump is enabled the iBeam fires for
        `_line_repump_duration` seconds before returning control so the
        scanner can proceed.

        @param bool start: True = new line starting, False = line just ended
        @param tuple scan_axes: Axes being scanned (forwarded from the signal)
        """
        if not self._line_repump_enabled:
            return
        if not start:
            # Signal fires twice per cycle; act only on the "about to start" edge.
            return

        hw = self._ibeam()
        try:
            hw.setPower(self._power_uW)
            hw.enable()
            time.sleep(self._line_repump_duration)
        finally:
            # Always restore CW state after repump pulse
            if self._cw_enabled:
                hw.setPower(self._power_uW)
                hw.enable()
            else:
                hw.disable()
