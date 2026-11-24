# -*- coding: utf-8 -*-
"""
Optical power-Rabi measurement on SnV centres (Bluefors lab).

Per data point:
  1. Pulse Streamer analog output (default A1, drives the AOM amplitude) is set to V_i.
  2. A periodic sequence is streamed exactly N times:
        D1 -> AOM gate, D3 -> PPG512 trigger (EOM pulse), D5 -> Time Tagger histogram start.
     Each digital channel has its own duration and time offset inside the period,
     exactly like the "Built-in / Pulse" mode of the Swabian Pulse Streamer GUI.
  3. A Time Tagger histogram (start = trigger channel, click = APD/SNSPD channel) collects
     the photons; the sum over a selectable bin window (ROI) is divided by the number of
     triggers actually seen by the Time Tagger -> counts per shot.
  4. Plotted against sqrt(V) (or sqrt(P) once a voltage->power calibration is loaded).

Power calibration (optional, needs a power meter in front of the cryostat):
  The same sequence is streamed continuously at each voltage and the power meter reads the
  average power P_avg(V). For a fixed pulse shape the pulse energy is P_avg * period, so
  sqrt(P_avg) is proportional to the pulse area, i.e. the correct Rabi x axis.
  Mode 'aom_cw' (AOM gate permanently open, PPG/TT off) is meant for characterising the AOM only.
  A dark reading (all outputs 0) is subtracted. The result is kept in a status variable
  (survives restarts) and can be saved; saved files can be loaded again (columns: V, P[W], ...).

Example config:

    power_rabi_logic:
        module.Class: 'power_rabi_logic.PowerRabiLogic'
        connect:
            pulsestreamer: 'pulsestreamer_api'
            tagger: 'tagger'
            powermeter: 'powermeter'     # optional, only needed for the power calibration
        options:
            max_analog_voltage: 1.0
            # power_calibration_file: 'Z:\\Vlad\\calibration\\aom_A1_V_to_P.dat'  # optional, 2 columns: V, P (W)
"""

import os
import time
import datetime as dt

import numpy as np
from PySide2 import QtCore

from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.core.module import LogicBase
from qudi.util.mutex import RecursiveMutex
from qudi.util.datastorage import TextDataStorage, ImageFormat


DEFAULT_SETTINGS = {
    # --- sequence (all times in ns) ---
    'period_ns': 1000,
    'aom_channel': 1, 'aom_duration_ns': 30, 'aom_offset_ns': 0,
    'ppg_channel': 3, 'ppg_duration_ns': 20, 'ppg_offset_ns': 520,
    'tt_channel': 5, 'tt_duration_ns': 50, 'tt_offset_ns': 655,
    'analog_channel': 1,
    # --- sweep ---
    'v_start': 0.0, 'v_stop': 1.0, 'n_points': 41,
    'sqrt_spacing': True,          # points equidistant in sqrt(V)
    'n_triggers': 1_000_000,       # sequence repetitions per data point
    'n_sweeps': 1,
    'preview_voltage': 0.33,
    # --- histogram ---
    'click_channel': 2, 'trigger_channel': 5,
    'bin_width_ps': 200, 'n_bins': 1000,
    'roi_start_ns': 0.0, 'roi_stop_ns': 200.0,
    # --- power calibration ---
    'cal_v_start': 0.0, 'cal_v_stop': 1.0, 'cal_n_points': 41,
    'cal_mode': 'sequence',        # 'sequence' (Rabi sequence) | 'aom_cw' (AOM gate open)
    'cal_settle_s': 0.5,           # wait after changing the voltage
    'cal_n_avg': 10,               # power meter readings averaged per point
    'cal_subtract_dark': True,
}


# settings that change the optical pulse train -> a calibration is only valid for these values
_SEQUENCE_KEYS = ('period_ns', 'analog_channel') + tuple(
    f'{n}_{k}' for n in ('aom', 'ppg', 'tt') for k in ('channel', 'duration_ns', 'offset_ns'))


class PowerRabiLogic(LogicBase):
    """ Optical power-Rabi: fluorescence vs. sqrt(excitation power). """

    _pulsestreamer = Connector(name='pulsestreamer', interface='PulseStreamer')
    _tagger = Connector(name='tagger', interface='TT')
    _powermeter = Connector(name='powermeter', interface='ProcessValueInterface', optional=True)

    _max_voltage = ConfigOption('max_analog_voltage', 1.0, missing='nothing')
    _calibration_file = ConfigOption('power_calibration_file', None, missing='nothing')
    _point_timeout_margin_s = ConfigOption('point_timeout_margin_s', 5.0, missing='nothing')

    _settings = StatusVar('settings', default=dict(DEFAULT_SETTINGS))
    _stored_calibration = StatusVar('power_calibration', default=None)

    # signals logic -> GUI
    sigDataUpdated = QtCore.Signal(object)        # dict with x/y arrays etc.
    sigHistogramUpdated = QtCore.Signal(object, object)   # time axis (ns), counts
    sigStateChanged = QtCore.Signal(str)          # 'idle' | 'running' | 'preview' | 'calibrating'
    sigProgress = QtCore.Signal(int, int, int, int)  # point, n_points, sweep, n_sweeps
    sigSettingsUpdated = QtCore.Signal(object)
    sigFitUpdated = QtCore.Signal(object)         # dict or None
    sigCalibrationUpdated = QtCore.Signal(object) # dict: voltage, power, power_std, ... or None
    sigCalProgress = QtCore.Signal(int, int)

    # internal
    _sigNextPoint = QtCore.Signal()
    _sigNextCalPoint = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = RecursiveMutex()
        self._state = 'idle'
        self._stop_requested = False
        self._hist = None
        self._trig_counter = None
        self._preview_timer = None
        self._calibration = None   # (V array, P array) used for the sqrt(P) axis
        self._cal_run = None       # data of the running / last calibration measurement
        self._fit_result = None
        self._reset_data()

    # ------------------------------------------------------------------ activation
    def on_activate(self):
        merged = dict(DEFAULT_SETTINGS)
        merged.update(self._settings or {})
        self._settings = merged

        self._preview_timer = QtCore.QTimer()
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._preview_poll)

        self._sigNextPoint.connect(self._measure_next_point, QtCore.Qt.QueuedConnection)
        self._sigNextCalPoint.connect(self._calibrate_next_point, QtCore.Qt.QueuedConnection)

        if self._calibration_file:
            self.load_power_calibration(self._calibration_file)
        elif self._stored_calibration:
            try:
                c = self._stored_calibration
                self._set_calibration(np.asarray(c['voltage'], float), np.asarray(c['power'], float),
                                      info=c, store=False)
                self.log.info(f'Restored power calibration from {c.get("timestamp", "?")} '
                              f'(mode {c.get("mode", "?")}).')
            except Exception as e:
                self.log.warning(f'Stored power calibration could not be restored: {e}')

    def on_deactivate(self):
        self._stop_requested = True
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer.timeout.disconnect()
        for sig in (self._sigNextPoint, self._sigNextCalPoint):
            try:
                sig.disconnect()
            except RuntimeError:
                pass
        self._release_powermeter()
        self._ps_off()
        self._free_tagger_measurements()

    # ------------------------------------------------------------------ properties
    @property
    def settings(self):
        return dict(self._settings)

    @property
    def state(self):
        return self._state

    @property
    def has_calibration(self):
        return self._calibration is not None

    # ------------------------------------------------------------------ settings
    @QtCore.Slot(object)
    def set_settings(self, new_settings):
        """ Update (a subset of) the settings. Ignored while a measurement is running. """
        if self._state in ('running', 'calibrating'):
            self.log.warning('Settings cannot be changed during a running measurement/calibration.')
            self.sigSettingsUpdated.emit(self.settings)
            return
        s = dict(self._settings)
        for key, val in dict(new_settings).items():
            if key in DEFAULT_SETTINGS:
                s[key] = type(DEFAULT_SETTINGS[key])(val)
        s['v_start'] = float(np.clip(s['v_start'], 0, self._max_voltage))
        s['v_stop'] = float(np.clip(s['v_stop'], 0, self._max_voltage))
        s['preview_voltage'] = float(np.clip(s['preview_voltage'], 0, self._max_voltage))
        self._settings = s
        self.sigSettingsUpdated.emit(self.settings)
        # live preview follows setting changes immediately
        if self._state == 'preview':
            try:
                self._setup_tagger_measurements(self._settings)
                self._start_preview_stream()
            except Exception as e:
                self.log.error(f'Updating live preview failed: {e}')
                self.stop_preview()

    def voltage_list(self, settings=None):
        s = self._settings if settings is None else settings
        n = max(int(s['n_points']), 2)
        if s['sqrt_spacing']:
            return np.linspace(np.sqrt(s['v_start']), np.sqrt(s['v_stop']), n) ** 2
        return np.linspace(s['v_start'], s['v_stop'], n)

    # ------------------------------------------------------------------ calibration
    def load_power_calibration(self, path):
        """ Load a text file with columns voltage [V], power [W] (further columns ignored),
        e.g. a file written by save_calibration(). """
        try:
            data = np.atleast_2d(np.loadtxt(path, comments='#'))
            self._set_calibration(data[:, 0], data[:, 1],
                                  info={'source_file': str(path), 'mode': 'file'})
            self.log.info(f'Power calibration loaded from {path} ({data.shape[0]} points).')
        except Exception as e:
            self.log.error(f'Could not load power calibration "{path}": {e}')

    def _set_calibration(self, voltage, power, info=None, store=True):
        order = np.argsort(voltage)
        v, p = np.asarray(voltage, float)[order], np.clip(np.asarray(power, float)[order], 0, None)
        if len(v) < 2:
            raise ValueError('A calibration needs at least 2 points.')
        self._calibration = (v, p)
        if store:
            entry = dict(info or {})
            entry.update({'voltage': v.tolist(), 'power': p.tolist()})
            entry.setdefault('timestamp', dt.datetime.now().isoformat(timespec='seconds'))
            self._stored_calibration = entry
        self._emit_calibration()
        self._emit_data()

    @QtCore.Slot()
    def clear_calibration(self):
        self._calibration = None
        self._stored_calibration = None
        self._emit_calibration()
        self._emit_data()

    def voltage_to_power(self, voltage):
        if self._calibration is None:
            return np.full_like(np.asarray(voltage, dtype=float), np.nan)
        v_cal, p_cal = self._calibration
        return np.interp(np.asarray(voltage, dtype=float), v_cal, p_cal)

    def _emit_calibration(self):
        run = self._cal_run
        out = {
            'active_voltage': None if self._calibration is None else self._calibration[0].copy(),
            'active_power': None if self._calibration is None else self._calibration[1].copy(),
            'active_info': {k: v for k, v in (self._stored_calibration or {}).items()
                            if k not in ('voltage', 'power')},
            'run': None if run is None else {k: (v.copy() if isinstance(v, np.ndarray) else v)
                                             for k, v in run.items()},
        }
        self.sigCalibrationUpdated.emit(out)

    def request_calibration_update(self):
        self._emit_calibration()

    # ------------------------------------------------------------------ hardware helpers
    def _ps_client(self):
        hw = self._pulsestreamer()
        client = getattr(hw, 'ps', None) or getattr(hw, 'pulse_streamer', None)
        if client is None:
            raise RuntimeError('Pulse Streamer not connected.')
        return client

    def _build_sequence(self, voltage, settings, mode='sequence'):
        """ Build one period of the pulse pattern as a pulsestreamer Sequence object.
        mode 'aom_cw': only the AOM gate, permanently open (for AOM characterisation). """
        import pulsestreamer as psapi   # imported here: only needed on the lab PC
        s = settings
        period = int(s['period_ns'])
        client = self._ps_client()
        seq = client.createSequence()

        used = {}
        for name in ('aom', 'ppg', 'tt'):
            ch = int(s[f'{name}_channel'])
            dur = int(s[f'{name}_duration_ns'])
            off = int(s[f'{name}_offset_ns'])
            if not 0 <= ch <= 7:
                raise ValueError(f'{name}: digital channel {ch} out of range 0..7')
            if ch in used:
                raise ValueError(f'{name} and {used[ch]} use the same digital channel {ch}')
            if dur <= 0 or off < 0 or off + dur > period:
                raise ValueError(f'{name}: pulse (offset {off} ns + duration {dur} ns) '
                                 f'does not fit into the period of {period} ns')
            used[ch] = name
            if mode == 'aom_cw':
                level = 1 if name == 'aom' else 0
                seq.setDigital(ch, [(period, level)])
                continue
            pattern = [(off, 0), (dur, 1), (period - off - dur, 0)]
            seq.setDigital(ch, [p for p in pattern if p[0] > 0])

        a_ch = int(s['analog_channel'])
        if a_ch not in (0, 1):
            raise ValueError('Analog channel must be 0 or 1')
        v = float(np.clip(voltage, 0, self._max_voltage))
        seq.setAnalog(a_ch, [(period, v)])
        return seq, psapi

    def _stream(self, voltage, n_runs, settings, mode='sequence'):
        seq, psapi = self._build_sequence(voltage, settings, mode)
        client = self._ps_client()
        client.setTrigger(start=psapi.TriggerStart.IMMEDIATE, rearm=psapi.TriggerRearm.MANUAL)
        # after the last repetition everything (incl. the AOM voltage) goes back to 0
        client.stream(seq, n_runs=n_runs, final=psapi.OutputState([], 0.0, 0.0))

    def _ps_off(self):
        try:
            import pulsestreamer as psapi
            self._ps_client().constant(psapi.OutputState([], 0.0, 0.0))
        except Exception as e:
            self.log.debug(f'Pulse Streamer off failed: {e}')

    def _setup_tagger_measurements(self, settings):
        self._free_tagger_measurements()
        tt = self._tagger()
        self._hist = tt.histogram(channel=int(settings['click_channel']),
                                  trigger_channel=int(settings['trigger_channel']),
                                  bin_width=int(settings['bin_width_ps']),
                                  number_of_bins=int(settings['n_bins']))
        try:
            self._trig_counter = tt.countrate(channels=[int(settings['trigger_channel'])])
        except Exception as e:
            self._trig_counter = None
            self.log.warning(f'Trigger counter not available, using nominal trigger number: {e}')

    def _free_tagger_measurements(self):
        for meas in (self._hist, self._trig_counter):
            if meas is not None:
                try:
                    meas.stop()
                except Exception:
                    pass
        self._hist = None
        self._trig_counter = None

    def _clear_tagger(self):
        self._hist.clear()
        if self._trig_counter is not None:
            self._trig_counter.clear()

    def _tagger_sync(self):
        """ Make sure all tags up to now have been processed (important for the network tagger). """
        try:
            self._tagger().tagger.sync()
        except Exception as e:
            self.log.debug(f'tagger.sync() failed, falling back to short wait: {e}')
            time.sleep(0.1)

    def _triggers_seen(self, nominal):
        if self._trig_counter is None:
            return float(nominal)
        try:
            return float(np.asarray(self._trig_counter.getCountsTotal()).ravel()[0])
        except Exception as e:
            self.log.warning(f'Reading trigger counter failed ({e}), using nominal number.')
            self._trig_counter = None
            return float(nominal)

    def _time_axis_ns(self, settings=None):
        s = self._settings if settings is None else settings
        return np.arange(int(s['n_bins'])) * s['bin_width_ps'] / 1e3

    def _roi_slice(self, settings):
        bw_ns = settings['bin_width_ps'] / 1e3
        n = int(settings['n_bins'])
        i0 = int(np.clip(np.floor(settings['roi_start_ns'] / bw_ns), 0, n))
        i1 = int(np.clip(np.ceil(settings['roi_stop_ns'] / bw_ns), 0, n))
        if i1 <= i0:
            i0, i1 = 0, n
        return slice(i0, i1)

    # ------------------------------------------------------------------ measurement
    def _reset_data(self):
        self.voltages = np.array([])
        self.roi_counts = np.array([])
        self.n_triggers = np.array([])
        self.histograms = np.zeros((0, 0))
        self._point_index = 0
        self._sweep_index = 0

    @QtCore.Slot()
    def start_measurement(self):
        with self._lock:
            if self._state in ('running', 'calibrating'):
                return
            if self._state == 'preview':
                self.stop_preview()
            self._run_settings = dict(self._settings)
            s = self._run_settings
            try:
                self._setup_tagger_measurements(s)
            except Exception as e:
                self.log.error(f'Could not set up Time Tagger measurement: {e}')
                return
            self.voltages = self.voltage_list(s)
            n = len(self.voltages)
            self.roi_counts = np.zeros(n)
            self.n_triggers = np.zeros(n)
            self.histograms = np.zeros((n, int(s['n_bins'])))
            self._point_index = 0
            self._sweep_index = 0
            self._fit_result = None
            self.sigFitUpdated.emit(None)
            self._stop_requested = False
            self._trigger_warning_given = False
            self._start_time = dt.datetime.now()
            self._set_state('running')
            if self.has_calibration:
                self._warn_if_settings_differ_from_calibration()
                v_cal = self._calibration[0]
                if self.voltages.min() < v_cal[0] - 1e-9 or self.voltages.max() > v_cal[-1] + 1e-9:
                    self.log.warning(f'Sweep exceeds the calibrated range {v_cal[0]:.3f}..'
                                     f'{v_cal[-1]:.3f} V; sqrt(P) is clamped outside of it.')
            self.log.info(f'Power Rabi started: {n} points, {s["n_triggers"]} triggers/point, '
                          f'{s["n_sweeps"]} sweep(s).')
        self._emit_data()
        self._sigNextPoint.emit()

    def stop_measurement(self):
        """ Thread-safe: may be called directly from the GUI thread. """
        self._stop_requested = True

    @QtCore.Slot()
    def _measure_next_point(self):
        if self._state != 'running':
            return
        if self._stop_requested:
            self._finish_measurement(aborted=True)
            return
        s = self._run_settings
        i = self._point_index
        voltage = self.voltages[i]
        n_runs = int(s['n_triggers'])
        try:
            self._clear_tagger()
            self._stream(voltage, n_runs, s)
            client = self._ps_client()
            timeout = n_runs * s['period_ns'] * 1e-9 + self._point_timeout_margin_s
            t0 = time.monotonic()
            while not client.hasFinished():
                if self._stop_requested:
                    self._ps_off()
                    self._finish_measurement(aborted=True)
                    return
                if time.monotonic() - t0 > timeout:
                    raise TimeoutError(f'Pulse Streamer did not finish within {timeout:.1f} s')
                time.sleep(0.01)
            self._tagger_sync()
            hist = np.asarray(self._hist.getData(), dtype=float).ravel()
            seen = self._triggers_seen(n_runs)
        except Exception as e:
            self.log.exception(f'Power Rabi point {i} (V={voltage:.4f}) failed: {e}')
            self._ps_off()
            self._finish_measurement(aborted=True)
            return

        if not self._trigger_warning_given and abs(seen - n_runs) > 0.01 * n_runs:
            self.log.warning(f'Time Tagger saw {seen:.0f} triggers on channel '
                             f'{s["trigger_channel"]}, expected {n_runs}. Check D{s["tt_channel"]} '
                             f'cabling / trigger level. Normalising to the triggers actually seen.')
            self._trigger_warning_given = True

        self.histograms[i] += hist
        self.roi_counts[i] += hist[self._roi_slice(s)].sum()
        self.n_triggers[i] += seen
        self.sigHistogramUpdated.emit(self._time_axis_ns(s), hist)
        self.sigProgress.emit(i + 1, len(self.voltages), self._sweep_index + 1, int(s['n_sweeps']))
        self._emit_data()

        self._point_index += 1
        if self._point_index >= len(self.voltages):
            self._point_index = 0
            self._sweep_index += 1
            if self._sweep_index >= int(s['n_sweeps']):
                self._finish_measurement(aborted=False)
                return
        self._sigNextPoint.emit()

    def _finish_measurement(self, aborted):
        self._ps_off()
        self._free_tagger_measurements()
        # the sum window may have been moved in the GUI during the run
        if self.histograms.size:
            self.roi_counts = self.histograms[:, self._roi_slice(self._settings)].sum(axis=1)
            self._emit_data()
        self._set_state('idle')
        self.log.info('Power Rabi ' + ('aborted.' if aborted else 'finished.'))

    @QtCore.Slot(float, float)
    def recalculate_roi(self, roi_start_ns, roi_stop_ns):
        """ Change the summation window and re-evaluate already measured histograms. """
        self._settings = dict(self._settings, roi_start_ns=float(roi_start_ns),
                              roi_stop_ns=float(roi_stop_ns))
        if self._state != 'running' and self.histograms.size:
            self.roi_counts = self.histograms[:, self._roi_slice(self._settings)].sum(axis=1)
            self._emit_data()
        self.sigSettingsUpdated.emit(self.settings)

    # ------------------------------------------------------------------ power calibration
    def _powermeter_hw(self):
        try:
            pm = self._powermeter()
        except Exception:
            pm = None
        if pm is None:
            raise RuntimeError('No power meter connected (connector "powermeter" in the config).')
        return pm

    def _activate_powermeter(self):
        """ Handles both Thorlabs drivers: TLPM (needs channel activation) and PM100D. """
        pm = self._powermeter_hw()
        self._pm_activated_by_us = False
        try:
            if not pm.get_activity_state('Power'):
                pm.set_activity_state('Power', True)
                self._pm_activated_by_us = True
        except (TypeError, AttributeError, AssertionError):
            pass   # PM100D: always active

    def _release_powermeter(self):
        if getattr(self, '_pm_activated_by_us', False):
            try:
                self._powermeter_hw().set_activity_state('Power', False)
            except Exception:
                pass
            self._pm_activated_by_us = False

    def _read_power(self):
        pm = self._powermeter_hw()
        try:
            value = pm.get_process_value('Power')
        except TypeError:
            value = pm.get_process_value()      # PM100D signature
        if isinstance(value, dict):
            value = value.get('Power', next(iter(value.values())))
        return float(value)

    def _read_power_avg(self, n_avg):
        vals = []
        for _ in range(max(int(n_avg), 1)):
            if self._stop_requested:
                break
            vals.append(self._read_power())
            time.sleep(0.02)
        vals = np.asarray(vals)
        return (float(vals.mean()), float(vals.std())) if vals.size else (np.nan, np.nan)

    def _interruptible_sleep(self, seconds):
        t_end = time.monotonic() + seconds
        while time.monotonic() < t_end:
            if self._stop_requested:
                return False
            time.sleep(0.02)
        return True

    @QtCore.Slot()
    def start_calibration(self):
        """ Voltage sweep with the power meter. The power meter must be in the beam. """
        with self._lock:
            if self._state != 'idle':
                self.log.warning('Calibration can only be started when idle.')
                return
            s = dict(self._settings)
            if s['cal_mode'] not in ('sequence', 'aom_cw'):
                self.log.error(f'Unknown calibration mode {s["cal_mode"]}')
                return
            try:
                self._activate_powermeter()
                self._build_sequence(0.0, s, s['cal_mode'])     # validates the timing
            except Exception as e:
                self.log.error(f'Power calibration cannot start: {e}')
                return
            self._stop_requested = False
            self._cal_settings = s
            n = max(int(s['cal_n_points']), 2)
            v = np.linspace(float(np.clip(s['cal_v_start'], 0, self._max_voltage)),
                            float(np.clip(s['cal_v_stop'], 0, self._max_voltage)), n)
            self._cal_run = {'voltage': v, 'power': np.full(n, np.nan), 'power_std': np.full(n, np.nan),
                             'dark': 0.0, 'dark_std': 0.0, 'mode': s['cal_mode'],
                             'finished': False}
            self._cal_index = 0
            self._cal_start = dt.datetime.now()
            self._set_state('calibrating')

        # dark reading: everything off
        self._ps_off()
        if s['cal_subtract_dark']:
            if not self._interruptible_sleep(s['cal_settle_s']):
                self._finish_calibration(aborted=True)
                return
            try:
                dark, dark_std = self._read_power_avg(s['cal_n_avg'])
            except Exception as e:
                self.log.error(f'Power meter reading failed: {e}')
                self._finish_calibration(aborted=True)
                return
            self._cal_run['dark'], self._cal_run['dark_std'] = dark, dark_std
            self.log.info(f'Power calibration: dark reading {dark * 1e9:.2f} nW')
        self._emit_calibration()
        self._sigNextCalPoint.emit()

    @QtCore.Slot()
    def _calibrate_next_point(self):
        if self._state != 'calibrating':
            return
        if self._stop_requested:
            self._finish_calibration(aborted=True)
            return
        s = self._cal_settings
        run = self._cal_run
        i = self._cal_index
        try:
            self._stream(run['voltage'][i], -1, s, s['cal_mode'])
            if not self._interruptible_sleep(s['cal_settle_s']):
                self._finish_calibration(aborted=True)
                return
            p, p_std = self._read_power_avg(s['cal_n_avg'])
        except Exception as e:
            self.log.exception(f'Calibration point {i} failed: {e}')
            self._finish_calibration(aborted=True)
            return
        run['power'][i] = p - run['dark']
        run['power_std'][i] = p_std
        self.sigCalProgress.emit(i + 1, len(run['voltage']))
        self._emit_calibration()
        self._cal_index += 1
        if self._cal_index >= len(run['voltage']):
            self._finish_calibration(aborted=False)
            return
        self._sigNextCalPoint.emit()

    def _finish_calibration(self, aborted):
        self._ps_off()
        self._release_powermeter()
        run = self._cal_run
        if not aborted and run is not None:
            run['finished'] = True
            s = self._cal_settings
            info = {'timestamp': self._cal_start.isoformat(timespec='seconds'), 'mode': run['mode'],
                    'dark_W': run['dark'], 'n_avg': s['cal_n_avg'], 'settle_s': s['cal_settle_s']}
            if run['mode'] == 'sequence':
                info.update({k: s[k] for k in _SEQUENCE_KEYS})
            self._set_calibration(run['voltage'], run['power'], info=info)
            p_max = np.nanmax(run['power'])
            self.log.info(f'Power calibration finished: max {p_max * 1e6:.3f} µW (avg). '
                          f'It is now used for the sqrt(P) axis.')
            if run['mode'] == 'sequence':
                self._warn_if_settings_differ_from_calibration()
        else:
            self.log.info('Power calibration aborted, previous calibration is kept.')
        self._set_state('idle')
        self._emit_calibration()

    def _warn_if_settings_differ_from_calibration(self):
        c = self._stored_calibration or {}
        if c.get('mode') != 'sequence':
            return
        diff = [k for k in _SEQUENCE_KEYS if k in c and self._settings[k] != c[k]]
        if diff:
            self.log.warning('Sequence settings differ from the ones used for the power calibration '
                             f'({", ".join(diff)}); the sqrt(P) axis may be off. Recalibrate.')

    @QtCore.Slot(str)
    def save_calibration(self, name_tag=''):
        run = self._cal_run
        if run is not None and np.isfinite(run['power']).any():
            v, p, p_std = run['voltage'], run['power'], run['power_std']
        elif self._calibration is not None:
            v, p = self._calibration
            p_std = np.full_like(p, np.nan)
        else:
            self.log.error('No calibration data to save.')
            return
        from matplotlib.figure import Figure
        meta = {k: val for k, val in (self._stored_calibration or {}).items()
                if k not in ('voltage', 'power')}
        if run is not None:
            meta.update({'mode': run['mode'], 'dark_W': run['dark'], 'dark_std_W': run['dark_std']})
        storage = TextDataStorage(root_dir=self.module_default_data_dir,
                                  comments='# ', delimiter='\t', file_extension='.dat',
                                  include_global_metadata=True, image_format=ImageFormat.PNG)
        tag = f'power_calibration_{name_tag}' if name_tag else 'power_calibration'
        headers = ['voltage (V)', 'power (W)', 'power_std (W)']
        file_path, _, _ = storage.save_data(np.column_stack((v, p, p_std)), metadata=meta,
                                            nametag=tag, timestamp=dt.datetime.now(),
                                            column_headers=headers, column_dtypes=[float] * 3)
        fig = Figure()
        ax = fig.add_subplot(111)
        ax.errorbar(v, np.asarray(p) * 1e6, yerr=np.asarray(p_std) * 1e6, fmt='o-', ms=3)
        ax.set_xlabel('analog voltage (V)')
        ax.set_ylabel('power (µW)')
        ax.set_title(f'Power calibration ({meta.get("mode", "")})')
        storage.save_thumbnail(fig, os.path.splitext(file_path)[0])
        self.log.info(f'Power calibration saved to {file_path}')

    # ------------------------------------------------------------------ live preview
    @QtCore.Slot()
    def start_preview(self):
        """ Stream the sequence continuously at the preview voltage and show the live histogram
        (like the Swabian GUIs) to align the channel delays. """
        if self._state != 'idle':
            return
        try:
            self._setup_tagger_measurements(self._settings)
            self._start_preview_stream()
        except Exception as e:
            self.log.error(f'Live preview failed: {e}')
            self._ps_off()
            self._free_tagger_measurements()
            return
        self._set_state('preview')
        self._preview_timer.start()

    def _start_preview_stream(self):
        self._stream(self._settings['preview_voltage'], -1, self._settings)
        if self._hist is not None:
            self._hist.clear()

    @QtCore.Slot()
    def stop_preview(self):
        if self._state != 'preview':
            return
        self._preview_timer.stop()
        self._ps_off()
        self._free_tagger_measurements()
        self._set_state('idle')

    def _preview_poll(self):
        if self._hist is None:
            return
        try:
            data = np.asarray(self._hist.getData(), dtype=float).ravel()
            self.sigHistogramUpdated.emit(self._time_axis_ns(), data)
        except Exception as e:
            self.log.error(f'Preview histogram read failed: {e}')
            self.stop_preview()

    # ------------------------------------------------------------------ data / fit / save
    def _x_data(self):
        return np.sqrt(self.voltages)

    def _emit_data(self):
        with np.errstate(divide='ignore', invalid='ignore'):
            y = np.where(self.n_triggers > 0, self.roi_counts / self.n_triggers, np.nan)
        power = self.voltage_to_power(self.voltages) if self.voltages.size else np.array([])
        self.sigDataUpdated.emit({
            'voltage': self.voltages.copy(),
            'sqrt_voltage': self._x_data(),
            'sqrt_power': np.sqrt(power) if self.has_calibration else None,
            'counts_per_trigger': y,
            'roi_counts': self.roi_counts.copy(),
            'n_triggers': self.n_triggers.copy(),
        })

    @QtCore.Slot()
    def do_fit(self):
        """ Damped cosine y = o - a*exp(-x/tau)*cos(2*pi*x/T + phi) on x = sqrt(V). """
        from scipy.optimize import curve_fit
        mask = self.n_triggers > 0
        if mask.sum() < 5:
            self.log.warning('Not enough data points for a fit.')
            return
        x = self._x_data()[mask]
        y = (self.roi_counts / np.where(self.n_triggers > 0, self.n_triggers, 1))[mask]

        def model(x, o, a, T, phi, tau):
            return o - a * np.exp(-x / tau) * np.cos(2 * np.pi * x / T + phi)

        # frequency guess from FFT of uniformly resampled data
        xu = np.linspace(x.min(), x.max(), 256)
        yu = np.interp(xu, x, y) - y.mean()
        freqs = np.fft.rfftfreq(len(xu), d=xu[1] - xu[0])
        spec = np.abs(np.fft.rfft(yu))
        f0 = freqs[1 + np.argmax(spec[1:])] if len(spec) > 1 else 1 / (x.max() - x.min())
        p0 = [y.mean(), (y.max() - y.min()) / 2, 1 / f0, 0.0, 10 * (x.max() - x.min())]
        try:
            popt, pcov = curve_fit(model, x, y, p0=p0, maxfev=20000,
                                   bounds=([-np.inf, 0, 1e-6, -np.pi, 1e-6],
                                           [np.inf, np.inf, np.inf, np.pi, np.inf]))
            perr = np.sqrt(np.diag(pcov))
        except Exception as e:
            self.log.warning(f'Fit failed: {e}')
            return
        o, a, T, phi, tau = popt
        x_pi = T / 2 - phi * T / (2 * np.pi)     # first maximum of the population
        x_fit = np.linspace(0, x.max(), 500)
        self._fit_result = {
            'params': dict(zip(('offset', 'amplitude', 'period_sqrtV', 'phase', 'decay_sqrtV'),
                               popt.tolist())),
            'errors': dict(zip(('offset', 'amplitude', 'period_sqrtV', 'phase', 'decay_sqrtV'),
                               perr.tolist())),
            'sqrtV_pi': float(x_pi),
            'V_pi': float(x_pi ** 2),
            'x_fit': x_fit,
            'y_fit': model(x_fit, *popt),
        }
        self.log.info(f'Power Rabi fit: pi pulse at sqrt(V)={x_pi:.4f}, V={x_pi**2:.4f} V')
        self.sigFitUpdated.emit(self._fit_result)

    @QtCore.Slot(str)
    def save_data(self, name_tag=''):
        if not self.voltages.size or not self.n_triggers.any():
            self.log.error('No data to save.')
            return
        from matplotlib.figure import Figure   # backend-free, safe outside the GUI thread

        s = self._run_settings if hasattr(self, '_run_settings') else self._settings
        timestamp = dt.datetime.now()
        with np.errstate(divide='ignore', invalid='ignore'):
            y = np.where(self.n_triggers > 0, self.roi_counts / self.n_triggers, np.nan)
        power = self.voltage_to_power(self.voltages)
        metadata = dict(s)
        metadata['start_time'] = getattr(self, '_start_time', timestamp).isoformat()
        metadata['power_calibration_loaded'] = self.has_calibration
        if self.has_calibration:
            metadata['power_calibration'] = {k: v for k, v in (self._stored_calibration or {}).items()
                                             if k not in ('voltage', 'power')}
        if self._fit_result is not None:
            metadata['fit_params'] = self._fit_result['params']
            metadata['fit_errors'] = self._fit_result['errors']
            metadata['fit_V_pi'] = self._fit_result['V_pi']

        storage = TextDataStorage(root_dir=self.module_default_data_dir,
                                  comments='# ', delimiter='\t', file_extension='.dat',
                                  include_global_metadata=True, image_format=ImageFormat.PNG)
        tag = f'power_rabi_{name_tag}' if name_tag else 'power_rabi'

        data = np.column_stack((self.voltages, np.sqrt(self.voltages), power,
                                self.roi_counts, self.n_triggers, y))
        headers = ['voltage (V)', 'sqrt_voltage (sqrt(V))', 'power (W)',
                   'roi_counts', 'n_triggers', 'counts_per_trigger']
        file_path, _, _ = storage.save_data(data, metadata=metadata, nametag=tag,
                                            timestamp=timestamp, column_headers=headers,
                                            column_dtypes=[float] * len(headers))

        fig = Figure()
        ax = fig.add_subplot(111)
        ax.plot(np.sqrt(self.voltages), y, 'o-', ms=4)
        if self._fit_result is not None:
            ax.plot(self._fit_result['x_fit'], self._fit_result['y_fit'], '-', lw=1.5)
        ax.set_xlabel(r'$\sqrt{V}$ ($\sqrt{\mathrm{V}}$)')
        ax.set_ylabel('counts per trigger')
        ax.set_title('Power Rabi')
        storage.save_thumbnail(fig, os.path.splitext(file_path)[0])

        # raw histograms: first column time axis, one column per voltage
        hist_data = np.column_stack((self._time_axis_ns(s), self.histograms.T))
        hist_headers = ['time (ns)'] + [f'V={v:.4f}' for v in self.voltages]
        storage.save_data(hist_data, metadata=metadata, nametag=tag + '_histograms',
                          timestamp=timestamp, column_headers=hist_headers,
                          column_dtypes=[float] * len(hist_headers))
        self.log.info(f'Power Rabi data saved to {file_path}')

    # ------------------------------------------------------------------ misc
    def _set_state(self, state):
        self._state = state
        self.sigStateChanged.emit(state)
