# -*- coding: utf-8 -*-
"""
Logic module for synchronized B-field sweeps with PLE scans.

The module ramps a vector magnet through generated XY/XZ/YZ trajectories and
triggers one PLE scan per B-field point. It emits progress/result signals for a
dockable GUI and provides summary saving via TextDataStorage.

Example config:

bfield_sweep_logic:
    module.Class: 'ple.bfield_sweep_logic.BFieldSweepLogic'
    connect:
        magnet: 'vector_magnet'
        ple_scanner: 'plescannerlogic'
        ple_data_logic: 'data_logic'  # optional
    options:
        default_fit_config: 'TwoLorentz'
        default_ple_repeats: 1
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use('Agg')  # non-interactive backend — safe in logic thread
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from PySide2 import QtCore

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.core.statusvariable import StatusVar
from qudi.util.datastorage import TextDataStorage, NpyDataStorage


class BFieldSweepLogic(LogicBase):
    """Run XY/XZ/YZ B-field sweeps synchronized to PLE scans."""

    _magnet = Connector(name="magnet", interface="Magnet3D")
    _ple_scanner = Connector(name="ple_scanner", interface="PLEScannerLogic")
    _ple_data_logic = Connector(
        name="ple_data_logic", interface="PleDataLogic", optional=True
    )

    _ramp_poll_interval_ms = ConfigOption(
        name="ramp_poll_interval_ms", default=250, missing="warn"
    )
    _field_poll_interval_ms = ConfigOption(
        name="field_poll_interval_ms", default=500, missing="warn"
    )
    _default_fit_config = ConfigOption(
        name="default_fit_config", default="TwoLorentz", missing="nothing"
    )
    _default_fit_channel = ConfigOption(
        name="default_fit_channel", default="", missing="nothing"
    )
    _default_scan_axis = ConfigOption(
        name="default_scan_axis", default="", missing="nothing"
    )
    _default_ple_repeats = ConfigOption(
        name="default_ple_repeats", default=1, missing="warn"
    )

    _last_settings = StatusVar(name="last_settings", default=None)

    sigSweepStateChanged = QtCore.Signal(bool)
    sigProgressChanged = QtCore.Signal(object)
    sigResultsChanged = QtCore.Signal(object)
    sigCurrentFieldChanged = QtCore.Signal(object)
    sigSaveFinished = QtCore.Signal(object)
    sigMessage = QtCore.Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._magnet_hw = None
        self._ple_scan_logic = None
        self._ple_data = None

        self._ramp_poll_timer = None
        self._field_poll_timer = None

        self._running = False
        self._abort_requested = False
        self._pending_ple_scan = False

        self._settings: Dict[str, Any] = {}
        self._scan_axes: Tuple[str, ...] = tuple()
        self._desired_ple_repeats = 1
        self._angles_deg = np.array([], dtype=float)
        self._target_points = np.empty((0, 3), dtype=float)
        self._point_index = -1
        self._results: List[Dict[str, Any]] = []

        self._current_target = np.zeros(3, dtype=float)
        self._last_scan_data = None
        self._sweep_started_at: Optional[dt.datetime] = None
        self._ple_repeats_backup: Optional[int] = None

    def on_activate(self):
        self._magnet_hw = self._magnet()
        self._ple_scan_logic = self._ple_scanner()
        self._ple_data = self._ple_data_logic() if self._ple_data_logic else None

        self._ramp_poll_timer = QtCore.QTimer(self)
        self._ramp_poll_timer.setInterval(max(10, int(self._ramp_poll_interval_ms)))
        self._ramp_poll_timer.timeout.connect(
            self._poll_ramp_state, QtCore.Qt.QueuedConnection
        )

        self._field_poll_timer = QtCore.QTimer(self)
        self._field_poll_timer.setInterval(max(50, int(self._field_poll_interval_ms)))
        self._field_poll_timer.timeout.connect(
            self._emit_current_field, QtCore.Qt.QueuedConnection
        )
        self._field_poll_timer.start()

        self._ple_scan_logic.sigScanStateChanged.connect(
            self._on_ple_scan_state_changed, QtCore.Qt.QueuedConnection
        )
        self._emit_current_field()

    def on_deactivate(self):
        self.stop_sweep()
        if self._ramp_poll_timer is not None:
            self._ramp_poll_timer.stop()
            self._ramp_poll_timer.timeout.disconnect()
            self._ramp_poll_timer = None
        if self._field_poll_timer is not None:
            self._field_poll_timer.stop()
            self._field_poll_timer.timeout.disconnect()
            self._field_poll_timer = None
        if self._ple_scan_logic is not None:
            try:
                self._ple_scan_logic.sigScanStateChanged.disconnect(
                    self._on_ple_scan_state_changed
                )
            except RuntimeError:
                pass

    @QtCore.Slot(result=object)
    def get_available_scan_axes(self):
        """Return all currently available PLE scan axes."""
        if self._ple_scan_logic is None:
            return tuple()
        return tuple(self._ple_scan_logic.scan_ranges.keys())

    @QtCore.Slot(result=object)
    def get_default_settings(self):
        """Return a default settings dictionary for the GUI."""
        if isinstance(self._last_settings, dict):
            defaults = dict(self._last_settings)
        else:
            defaults = {
                "plane": "XY",
                "amplitude_t": 0.2,
                "steps": 121,
                "start_angle_deg": 0.0,
                "stop_angle_deg": 360.0,
                "bx_offset_t": 0.0,
                "by_offset_t": 0.0,
                "bz_offset_t": 0.0,
                "fit_config": self._default_fit_config,
                "fit_channel": self._default_fit_channel,
                "fit_averaged": False,
                "do_fit": True,
                "ple_repeats": int(self._default_ple_repeats),
                "save_each_ple_scan": False,
                "auto_save": False,
                "save_last_ple": True,
                "tag": "",
            }
        if "scan_axis" not in defaults:
            defaults["scan_axis"] = self._default_scan_axis
        return defaults

    @QtCore.Slot(object)
    def start_sweep(self, settings):
        """Start a synchronized B-field sweep."""
        if self._running or self.module_state() != "idle":
            self.sigMessage.emit("B-field sweep is already running.")
            return
        if self._ple_scan_logic.module_state() != "idle":
            self.sigMessage.emit("PLE scanner is busy. Stop PLE scan before sweeping.")
            return

        try:
            sanitized = self._sanitize_settings(settings)
            targets, angles_deg = self._generate_targets(sanitized)
            if targets.size == 0:
                self.sigMessage.emit("No sweep points generated.")
                return
        except Exception:
            self.log.exception("Failed to prepare sweep settings.")
            self.sigMessage.emit("Failed to start sweep. Check sweep settings.")
            return

        self._settings = sanitized
        self._last_settings = dict(sanitized)
        self._angles_deg = angles_deg
        self._target_points = targets
        self._point_index = -1
        self._results = []
        self._last_scan_data = None
        self._current_target = np.zeros(3, dtype=float)
        self._abort_requested = False
        self._pending_ple_scan = False
        self._sweep_started_at = dt.datetime.now()
        self._scan_axes = (self._resolve_scan_axis(sanitized),)
        self._desired_ple_repeats = int(max(1, sanitized["ple_repeats"]))

        try:
            self._ple_repeats_backup = int(
                getattr(self._ple_scan_logic, "_number_of_repeats", 1)
            )
        except Exception:
            self._ple_repeats_backup = None

        try:
            self._ple_scan_logic.update_number_of_repeats(
                self._desired_ple_repeats
            )
            if hasattr(self._ple_scan_logic, "_repeated"):
                self._ple_scan_logic._repeated = 0
            if hasattr(self._ple_scan_logic, "display_repeated"):
                self._ple_scan_logic.display_repeated = 0
        except Exception:
            self.log.exception("Could not update PLE repeats.")

        self.module_state.lock()
        self._running = True
        self.sigSweepStateChanged.emit(True)
        self.sigResultsChanged.emit(self._result_payload())
        self.sigMessage.emit(
            f'Starting {sanitized["plane"]} sweep with {len(self._target_points)} points.'
        )
        self._advance_to_next_point()

    @QtCore.Slot()
    def stop_sweep(self):
        """Abort an active sweep."""
        if not self._running and self.module_state() == "idle":
            return
        self._abort_requested = True

        if self._ramp_poll_timer is not None:
            self._ramp_poll_timer.stop()

        try:
            if hasattr(self._magnet_hw, "pause_ramp"):
                self._magnet_hw.pause_ramp()
        except Exception:
            self.log.exception("Failed to pause magnet ramp while stopping sweep.")

        if self._pending_ple_scan:
            try:
                self._ple_scan_logic.toggle_scan(False, self._scan_axes, self.module_uuid)
            except Exception:
                self.log.exception("Failed to stop running PLE scan during sweep abort.")

        self._finish_sweep(aborted=True)

    @QtCore.Slot(str, object, bool)
    def save_results(self, tag="", root_dir=None, include_last_ple=False):
        """Save accumulated sweep results and optionally latest PLE trace."""
        if len(self._results) == 0:
            self.sigMessage.emit("No B-field sweep data to save.")
            return

        save_root = None if root_dir in (None, "", "Default") else str(root_dir)
        ds = TextDataStorage(
            root_dir=self.module_default_data_dir if save_root is None else save_root
        )
        timestamp = dt.datetime.now()

        angles = np.asarray([res["angle_deg"] for res in self._results], dtype=float)
        idx = np.asarray([res["index"] for res in self._results], dtype=float)
        target = np.asarray([res["target_field_t"] for res in self._results], dtype=float)
        actual = np.asarray([res["actual_field_t"] for res in self._results], dtype=float)
        target_sph = np.asarray(
            [res["target_spherical"] for res in self._results], dtype=float
        )
        actual_sph = np.asarray(
            [res["actual_spherical"] for res in self._results], dtype=float
        )
        peak_counts = np.asarray([res["peak_counts"] for res in self._results], dtype=float)
        fit_center = np.asarray([res["fit_center"] for res in self._results], dtype=float)
        fit_center_1 = np.asarray(
            [res["fit_center_1"] for res in self._results], dtype=float
        )
        fit_center_2 = np.asarray(
            [res["fit_center_2"] for res in self._results], dtype=float
        )
        fit_r2 = np.asarray([res["fit_r_squared"] for res in self._results], dtype=float)

        data = np.column_stack(
            (
                idx,
                angles,
                target[:, 0],
                target[:, 1],
                target[:, 2],
                actual[:, 0],
                actual[:, 1],
                actual[:, 2],
                target_sph[:, 0],
                target_sph[:, 1],
                target_sph[:, 2],
                actual_sph[:, 0],
                actual_sph[:, 1],
                actual_sph[:, 2],
                peak_counts,
                fit_center,
                fit_center_1,
                fit_center_2,
                fit_r2,
            )
        )

        metadata = self._build_metadata()
        save_tag = str(tag).strip()
        name_tag = "bfield_sweep" if not save_tag else f"bfield_sweep_{save_tag}"
        file_path, _, _ = ds.save_data(
            data,
            metadata=metadata,
            nametag=name_tag,
            timestamp=timestamp,
            column_headers=(
                "index,angle_deg,target_bx_t,target_by_t,target_bz_t,"
                "actual_bx_t,actual_by_t,actual_bz_t,"
                "target_r_t,target_theta_deg,target_phi_deg,"
                "actual_r_t,actual_theta_deg,actual_phi_deg,"
                "peak_counts,fit_center,fit_center_1,fit_center_2,fit_rsquared"
            ),
        )

        saved = {"summary_file": file_path}

        # Save the full PLE matrix (all scan traces stacked by angle)
        matrix_files = self._save_ple_matrix(
            name_tag=name_tag,
            timestamp=timestamp,
            ds=ds,
            save_root=save_root,
            metadata=metadata,
        )
        if matrix_files:
            saved["matrix_files"] = matrix_files

        if include_last_ple and self._last_scan_data is not None:
            ple_saved = self._save_ple_snapshot(
                scan_data=self._last_scan_data,
                tag=f"{name_tag}_last_ple",
                root_dir=save_root,
                extra_metadata={"linked_summary_file": file_path},
            )
            if ple_saved is not None:
                saved["ple_files"] = ple_saved

        self.sigSaveFinished.emit(saved)
        self.sigMessage.emit(f"Saved B-field sweep summary to: {file_path}")
        return saved

    def _save_ple_matrix(self, name_tag, timestamp, ds, save_root, metadata):
        """Build a 2-D PLE matrix (rows=angles, cols=scan-axis) and save to disk.

        Returns a dict with the paths of the saved files, or an empty dict on failure.
        """
        try:
            # ----------------------------------------------------------------
            # Collect traces, interpolating onto a common x-axis
            # ----------------------------------------------------------------
            traces = []
            angles = []
            x_axis_ref = None
            x_unit = ""
            x_name = ""

            for res in self._results:
                y = np.asarray(res.get("scan_signal", []), dtype=float).ravel()
                x = np.asarray(res.get("scan_axis_values", []), dtype=float).ravel()
                angle = float(res.get("angle_deg", np.nan))

                if y.size == 0 or not np.isfinite(angle):
                    continue

                # Make x and y the same length
                if x.size != y.size:
                    if x.size > 1:
                        x = np.linspace(x[0], x[-1], y.size, dtype=float)
                    else:
                        x = np.arange(y.size, dtype=float)

                # Sort ascending
                if x.size > 1 and x[1] < x[0]:
                    x = x[::-1]
                    y = y[::-1]

                if x_axis_ref is None:
                    x_axis_ref = x
                    x_unit = str(res.get("scan_axis_unit", "")).strip()
                    x_name = str(res.get("scan_axis_name", "freq")).strip()
                    traces.append(y)
                    angles.append(angle)
                    continue

                # Interpolate onto the reference x-axis if needed
                if y.size != x_axis_ref.size:
                    try:
                        sort_idx = np.argsort(x)
                        y = np.interp(
                            x_axis_ref,
                            x[sort_idx],
                            y[sort_idx],
                            left=np.nan,
                            right=np.nan,
                        )
                    except Exception:
                        common = int(min(x_axis_ref.size, y.size))
                        x_axis_ref = x_axis_ref[:common]
                        traces = [t[:common] for t in traces]
                        y = y[:common]

                traces.append(y)
                angles.append(angle)

            if len(traces) == 0 or x_axis_ref is None:
                return {}

            matrix = np.asarray(traces, dtype=float)   # shape (n_angles, n_freq)
            angles_arr = np.asarray(angles, dtype=float)

            # Sort by angle
            sort_order = np.argsort(angles_arr)
            angles_arr = angles_arr[sort_order]
            matrix = matrix[sort_order, :]

            # ----------------------------------------------------------------
            # Save matrix as .npy  (lossless, fast to reload)
            # ----------------------------------------------------------------
            npy_root = self.module_default_data_dir if save_root is None else save_root
            nds = NpyDataStorage(root_dir=npy_root)
            matrix_npy_path, _, _ = nds.save_data(
                matrix,
                nametag=f"{name_tag}_matrix",
                timestamp=timestamp,
                metadata=metadata,
                column_headers=(
                    f"PLE matrix: rows=angle_deg (n={len(angles_arr)}), "
                    f"cols={x_name or 'scan_axis'} (n={x_axis_ref.size})"
                ),
            )

            # ----------------------------------------------------------------
            # Save x-axis (frequencies) as .dat text
            # ----------------------------------------------------------------
            x_header = (
                f"{x_name or 'scan_axis'}"
                + (f"_{x_unit}" if x_unit else "")
            )
            x_path, _, _ = ds.save_data(
                x_axis_ref.reshape(-1, 1),
                metadata=metadata,
                nametag=f"{name_tag}_matrix_xaxis",
                timestamp=timestamp,
                column_headers=x_header,
            )

            # ----------------------------------------------------------------
            # Save angle axis as .dat text
            # ----------------------------------------------------------------
            ang_path, _, _ = ds.save_data(
                angles_arr.reshape(-1, 1),
                metadata=metadata,
                nametag=f"{name_tag}_matrix_angles",
                timestamp=timestamp,
                column_headers="angle_deg",
            )

            self.sigMessage.emit(
                f"Saved PLE matrix ({matrix.shape[0]} angles \u00d7 "
                f"{matrix.shape[1]} points) to: {matrix_npy_path}"
            )

            # ----------------------------------------------------------------
            # Render and save a figure — matrix image + parameter annotation
            # ----------------------------------------------------------------
            figure_path = None
            try:
                fig = self._draw_matrix_figure(
                    matrix=matrix,
                    angles=angles_arr,
                    x_axis=x_axis_ref,
                    x_name=x_name,
                    x_unit=x_unit,
                    metadata=metadata,
                )
                # save_thumbnail expects the path WITHOUT extension;
                # it appends the configured image format and closes the figure.
                thumb_base = matrix_npy_path.rsplit('.', 1)[0]
                figure_path = ds.save_thumbnail(fig, file_path=thumb_base)
            except Exception:
                self.log.exception('Failed to render PLE matrix figure.')

            result = {
                "matrix_npy": matrix_npy_path,
                "x_axis_dat": x_path,
                "angles_dat": ang_path,
            }
            if figure_path is not None:
                result["figure_png"] = figure_path
            return result

        except Exception:
            self.log.exception("Failed to save PLE matrix.")
            return {}

    def _draw_matrix_figure(self, matrix, angles, x_axis, x_name, x_unit, metadata=None):
        """Render the PLE matrix as a matplotlib figure with a parameter sidebar.

        The layout mirrors what is visible in the B-field sweep GUI:
        • Left: colour-mesh of signal vs (angle × scan-axis frequency)
        • Right: parameter box with all sweep settings from self._settings
        """
        s = self._settings  # shorthand
        m = metadata or {}  # for timestamps

        # ---- figure layout --------------------------------------------------
        fig = plt.figure(figsize=(12, 6), constrained_layout=False)
        fig.patch.set_facecolor('#1a1a2e')

        # Two columns: matrix (wide) + parameter panel (narrow)
        gs = fig.add_gridspec(
            1, 2,
            width_ratios=[3, 1],
            left=0.07, right=0.98,
            top=0.92, bottom=0.10,
            wspace=0.35,
        )
        ax_img  = fig.add_subplot(gs[0])
        ax_info = fig.add_subplot(gs[1])

        # ---- colour-mesh ----------------------------------------------------
        ax_img.set_facecolor('#0d0d1a')

        # Scale x-axis to best SI prefix
        x_vals = x_axis.copy()
        x_scale, x_prefix = 1.0, ''
        if x_vals.size > 1:
            x_range = abs(x_vals[-1] - x_vals[0])
            if x_range >= 1e12:
                x_scale, x_prefix = 1e12, 'T'
            elif x_range >= 1e9:
                x_scale, x_prefix = 1e9,  'G'
            elif x_range >= 1e6:
                x_scale, x_prefix = 1e6,  'M'
            elif x_range >= 1e3:
                x_scale, x_prefix = 1e3,  'k'
            elif x_range >= 1.0:
                x_scale, x_prefix = 1.0,  ''
            elif x_range >= 1e-3:
                x_scale, x_prefix = 1e-3, 'm'
        x_vals_scaled = x_vals / x_scale

        # Build a regular grid for pcolormesh
        if x_vals_scaled.size > 1:
            dx = (x_vals_scaled[-1] - x_vals_scaled[0]) / (x_vals_scaled.size - 1)
            x_edges = np.append(x_vals_scaled - dx / 2, x_vals_scaled[-1] + dx / 2)
        else:
            x_edges = np.array([x_vals_scaled[0] - 0.5, x_vals_scaled[0] + 0.5])

        if angles.size > 1:
            da = (angles[-1] - angles[0]) / (angles.size - 1)
            y_edges = np.append(angles - da / 2, angles[-1] + da / 2)
        else:
            y_edges = np.array([angles[0] - 0.5, angles[0] + 0.5])

        pcm = ax_img.pcolormesh(
            x_edges, y_edges, matrix,
            cmap='RdBu_r', shading='flat',
            rasterized=True,
        )

        cbar = fig.colorbar(pcm, ax=ax_img, pad=0.02, fraction=0.04)
        cbar.set_label('Signal (arb.)', color='#cdd6f4', fontsize=9)
        cbar.ax.yaxis.set_tick_params(color='#cdd6f4', labelsize=8)
        plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='#cdd6f4')

        x_label = f"{x_name or 'Scan axis'}"
        if x_unit:
            x_label += f" ({x_prefix}{x_unit})"
        elif x_prefix:
            x_label += f" ({x_prefix})"
        ax_img.set_xlabel(x_label, color='#cdd6f4', fontsize=10)
        ax_img.set_ylabel('B-field angle (deg)', color='#cdd6f4', fontsize=10)
        ax_img.tick_params(colors='#888aaa', labelsize=8)
        for spine in ax_img.spines.values():
            spine.set_edgecolor('#44445a')

        # Title
        plane  = str(s.get('plane', '?')).upper()
        amp_t  = float(s.get('amplitude_t', float('nan')))
        n_done = int(matrix.shape[0])
        n_tot  = int(s.get('steps', n_done))
        ax_img.set_title(
            f"PLE Matrix  —  {plane} plane, B = {amp_t*1e3:.2f} mT,  "
            f"{n_done}/{n_tot} points",
            color='#cdd6f4', fontsize=11, pad=8,
        )

        # ---- parameter panel ------------------------------------------------
        ax_info.set_facecolor('#12121f')
        ax_info.set_axis_off()

        def _fmt_t(v):
            """Format Tesla value nicely."""
            try:
                v = float(v)
                return f"{v*1e3:.3f} mT" if abs(v) < 1.0 else f"{v:.4f} T"
            except Exception:
                return str(v)

        def _fmt_v(v):
            try:
                f = float(v)
                if f == int(f):
                    return str(int(f))
                return f"{f:.4g}"
            except Exception:
                return str(v)

        # Collect parameter rows  (label, value)
        a_start = float(s.get('start_angle_deg', float('nan')))
        a_stop  = float(s.get('stop_angle_deg',  float('nan')))
        steps   = int(s.get('steps', n_done))
        bx_off  = float(s.get('bx_offset_t', 0.0))
        by_off  = float(s.get('by_offset_t', 0.0))
        bz_off  = float(s.get('bz_offset_t', 0.0))
        scan_ax = str(s.get('scan_axis', '')).strip() or 'auto'
        fit_cfg = str(s.get('fit_config', '')).strip() or 'none'
        fit_ch  = str(s.get('fit_channel', '')).strip() or 'auto'
        repeats = int(s.get('ple_repeats', 1))
        do_fit  = bool(s.get('do_fit', True))
        started = str(m.get('started_at', s.get('started_at', ''))).strip() or ''
        saved   = str(m.get('saved_at',   s.get('saved_at', dt.datetime.now().isoformat()))).strip()

        rows = [
            ('Plane',     plane),
            ('Amplitude', _fmt_t(amp_t)),
            ('Start \u03b1', f'{a_start:.2f}\u00b0'),
            ('Stop \u03b1',  f'{a_stop:.2f}\u00b0'),
            ('Steps',     str(steps)),
            ('Points done', str(n_done)),
            ('Bx offset',  _fmt_t(bx_off)),
            ('By offset',  _fmt_t(by_off)),
            ('Bz offset',  _fmt_t(bz_off)),
            ('Scan axis',  scan_ax),
            ('Fit config', fit_cfg),
            ('Fit channel', fit_ch),
            ('Fit enabled', 'yes' if do_fit else 'no'),
            ('PLE repeats', str(repeats)),
        ]
        if started:
            rows.append(('Started', started[:19].replace('T', '  ')))
        rows.append(('Saved',  saved[:19].replace('T', '  ')))

        n_rows = len(rows)
        row_h  = 1.0 / (n_rows + 1)
        y      = 1.0 - row_h * 0.6

        ax_info.text(
            0.5, y + row_h * 0.4, 'Sweep Parameters',
            ha='center', va='center',
            fontsize=9, fontweight='bold', color='#cdd6f4',
            transform=ax_info.transAxes,
        )
        ax_info.axhline(
            y=y + row_h * 0.1,
            xmin=0.02, xmax=0.98,
            color='#44445a', linewidth=0.8,
        )
        y -= row_h

        for label, value in rows:
            ax_info.text(
                0.02, y, f"{label}:",
                ha='left', va='center', fontsize=8,
                color='#888aaa', transform=ax_info.transAxes,
            )
            ax_info.text(
                0.98, y, value,
                ha='right', va='center', fontsize=8,
                color='#cdd6f4', transform=ax_info.transAxes,
                fontfamily='monospace',
            )
            y -= row_h

        return fig

    @QtCore.Slot()
    def _emit_current_field(self):
        field = self._safe_get_current_field()
        spherical = self._cartesian_to_spherical(field)
        ramping_state = self._safe_get_ramping_state()
        payload = {
            "field": field,
            "spherical": spherical,
            "ramping_state": ramping_state,
        }
        self.sigCurrentFieldChanged.emit(payload)

    @QtCore.Slot()
    def _poll_ramp_state(self):
        if not self._running:
            if self._ramp_poll_timer is not None:
                self._ramp_poll_timer.stop()
            return
        if self._abort_requested:
            self._finish_sweep(aborted=True)
            return

        ramp_states = self._safe_get_ramping_state()
        done = len(ramp_states) == 3 and all(int(s) in (2, 8) for s in ramp_states)
        self.sigProgressChanged.emit(
            self._progress_payload(stage="ramping", ramping_state=ramp_states)
        )
        if done:
            self._ramp_poll_timer.stop()
            self._start_ple_scan_for_current_point()

    @QtCore.Slot(bool, object, object)
    def _on_ple_scan_state_changed(self, is_running, scan_data, caller_id):
        if caller_id != self.module_uuid:
            return
        if not self._running:
            return

        if scan_data is not None:
            self._last_scan_data = scan_data

        if is_running:
            self.sigProgressChanged.emit(self._progress_payload(stage="scanning"))
            return
        if not self._pending_ple_scan:
            return

        self._pending_ple_scan = False
        if self._abort_requested:
            self._finish_sweep(aborted=True)
            return
        self._consume_scan_result(self._last_scan_data)

    def _advance_to_next_point(self):
        if not self._running:
            return
        if self._abort_requested:
            self._finish_sweep(aborted=True)
            return

        self._point_index += 1
        if self._point_index >= len(self._target_points):
            self._finish_sweep(aborted=False)
            return

        self._current_target = self._target_points[self._point_index].copy()
        self._last_scan_data = None
        try:
            self._magnet_hw.ramp(field_target=self._current_target)
        except TypeError:
            self._magnet_hw.ramp(self._current_target, False)
        except Exception:
            self.log.exception("Failed to ramp magnet to target field.")
            self._finish_sweep(
                aborted=True,
                error_message="Magnet ramp command failed. Sweep aborted.",
            )
            return

        self.sigProgressChanged.emit(self._progress_payload(stage="ramping"))
        self._ramp_poll_timer.start()

    def _start_ple_scan_for_current_point(self):
        if not self._running:
            return
        if self._abort_requested:
            self._finish_sweep(aborted=True)
            return
        if self._ple_scan_logic.module_state() != "idle":
            QtCore.QTimer.singleShot(
                int(max(10, self._ramp_poll_interval_ms)),
                self._start_ple_scan_for_current_point,
            )
            return

        self._pending_ple_scan = True
        try:
            self._ple_scan_logic.update_number_of_repeats(self._desired_ple_repeats)
            if hasattr(self._ple_scan_logic, "_repeated"):
                self._ple_scan_logic._repeated = 0
            if hasattr(self._ple_scan_logic, "display_repeated"):
                self._ple_scan_logic.display_repeated = 0
            self._ple_scan_logic.toggle_scan(True, self._scan_axes, self.module_uuid)
        except Exception:
            self.log.exception("Failed to start synchronized PLE scan.")
            self._pending_ple_scan = False
            self._finish_sweep(
                aborted=True, error_message="Unable to start PLE scan. Sweep aborted."
            )
            return
        self.sigProgressChanged.emit(self._progress_payload(stage="scanning"))

    def _consume_scan_result(self, scan_data):
        channel = self._resolve_channel(scan_data)
        scan_signal = self._extract_scan_trace(scan_data, channel)
        scan_axis_values = self._extract_scan_axis_values(scan_data, scan_signal.size)
        scan_axis_unit = self._extract_scan_axis_unit(scan_data)
        scan_axis_name = self._extract_scan_axis_name(scan_data)

        fit_center = np.nan
        fit_center_1 = np.nan
        fit_center_2 = np.nan
        fit_r2 = np.nan

        if (
            self._settings.get("do_fit", True)
            and scan_data is not None
            and channel is not None
            and self._settings.get("fit_config", "No Fit") != "No Fit"
        ):
            try:
                self._ple_scan_logic.do_fit(
                    self._settings["fit_config"],
                    channel,
                    bool(self._settings.get("fit_averaged", False)),
                )
                fit_dict = self._ple_scan_logic.fit_results
                fit_tuple = fit_dict.get(channel)
            except Exception:
                self.log.exception("PLE fit failed during sweep point processing.")
                fit_tuple = None
            fit_center, fit_center_1, fit_center_2, fit_r2 = self._extract_fit_values(
                fit_tuple
            )

        peak_counts = self._extract_peak_counts(scan_data, channel)
        actual_field = self._safe_get_current_field()
        target_spherical = self._cartesian_to_spherical(self._current_target)
        actual_spherical = self._cartesian_to_spherical(actual_field)

        result = {
            "index": int(self._point_index),
            "angle_deg": float(self._angles_deg[self._point_index]),
            "target_field_t": self._current_target.copy(),
            "actual_field_t": actual_field.copy(),
            "target_spherical": target_spherical.copy(),
            "actual_spherical": actual_spherical.copy(),
            "peak_counts": float(peak_counts),
            "fit_center": float(fit_center),
            "fit_center_1": float(fit_center_1),
            "fit_center_2": float(fit_center_2),
            "fit_r_squared": float(fit_r2),
            "fit_channel": channel,
            "scan_axis_name": scan_axis_name,
            "scan_axis_unit": scan_axis_unit,
            "scan_axis_values": scan_axis_values.copy(),
            "scan_signal": scan_signal.copy(),
            "timestamp": dt.datetime.now().isoformat(),
        }
        self._results.append(result)

        if self._settings.get("save_each_ple_scan", False) and scan_data is not None:
            step_tag = "{}_{:03d}".format(
                self._settings.get("plane", "plane"), self._point_index
            )
            self._save_ple_snapshot(
                scan_data=scan_data,
                tag=step_tag,
                root_dir=self._settings.get("root_dir"),
                extra_metadata={
                    "sweep_angle_deg": result["angle_deg"],
                    "target_bx_t": result["target_field_t"][0],
                    "target_by_t": result["target_field_t"][1],
                    "target_bz_t": result["target_field_t"][2],
                    "fit_center": result["fit_center"],
                    "fit_rsquared": result["fit_r_squared"],
                },
            )

        self.sigResultsChanged.emit(self._result_payload())
        self.sigProgressChanged.emit(self._progress_payload(stage="point_done"))
        QtCore.QTimer.singleShot(0, self._advance_to_next_point)

    def _finish_sweep(self, aborted=False, error_message=None):
        if not self._running and self.module_state() == "idle":
            return

        if self._ramp_poll_timer is not None:
            self._ramp_poll_timer.stop()
        self._pending_ple_scan = False
        self._running = False
        self._abort_requested = False

        if self._ple_repeats_backup is not None:
            try:
                self._ple_scan_logic.update_number_of_repeats(self._ple_repeats_backup)
            except Exception:
                self.log.exception("Failed to restore original PLE repeat setting.")
        self._ple_repeats_backup = None

        if self.module_state() != "idle":
            self.module_state.unlock()

        if self._settings.get("auto_save", False) and len(self._results) > 0 and not aborted:
            try:
                self.save_results(
                    tag=self._settings.get("tag", ""),
                    root_dir=self._settings.get("root_dir"),
                    include_last_ple=bool(self._settings.get("save_last_ple", True)),
                )
            except Exception:
                self.log.exception("Automatic save failed at sweep end.")

        stage = "aborted" if aborted else "finished"
        self.sigProgressChanged.emit(self._progress_payload(stage=stage))
        self.sigResultsChanged.emit(self._result_payload())
        self.sigSweepStateChanged.emit(False)

        if error_message:
            self.sigMessage.emit(error_message)
        elif aborted:
            self.sigMessage.emit("B-field sweep aborted.")
        else:
            self.sigMessage.emit("B-field sweep finished.")

    def _save_ple_snapshot(self, scan_data, tag, root_dir=None, extra_metadata=None):
        if scan_data is None or self._ple_data is None:
            return None
        try:
            fit_container = self._ple_scan_logic.fit_container
        except Exception:
            fit_container = None
        try:
            current_channel = self._resolve_channel(scan_data)
            self._ple_data.save_scan(
                scan_data,
                current_channel=current_channel,
                fit_container=fit_container,
                color_range=None,
                tag=tag,
                root_dir=root_dir,
                control_parameters={} if extra_metadata is None else dict(extra_metadata),
            )
            return dict(self._ple_data.last_saved_files_paths)
        except Exception:
            self.log.exception("Saving synchronized PLE data failed.")
            return None

    def _resolve_scan_axis(self, settings):
        available = self.get_available_scan_axes()
        if len(available) == 0:
            raise RuntimeError("No PLE scan axes available.")
        preferred = str(settings.get("scan_axis", "")).strip()
        if preferred and preferred in available:
            return preferred
        if self._default_scan_axis and self._default_scan_axis in available:
            return self._default_scan_axis
        return available[0]

    def _resolve_channel(self, scan_data):
        if scan_data is None:
            return None
        channel_names = list(scan_data.data.keys())
        if len(channel_names) == 0:
            return None
        preferred = str(self._settings.get("fit_channel", "")).strip()
        if preferred and preferred in channel_names:
            return preferred
        default = str(self._default_fit_channel).strip()
        if default and default in channel_names:
            return default
        return channel_names[0]

    def _extract_peak_counts(self, scan_data, channel):
        if scan_data is None or channel is None:
            return np.nan
        try:
            y_data = np.asarray(scan_data.data[channel], dtype=float).ravel()
            if y_data.size == 0:
                return np.nan
            return float(np.nanmax(y_data))
        except Exception:
            return np.nan

    def _extract_scan_trace(self, scan_data, channel):
        if scan_data is None or channel is None:
            return np.array([], dtype=float)
        try:
            accumulated = getattr(scan_data, "accumulated", None)
            if isinstance(accumulated, dict) and channel in accumulated:
                acc_data = np.asarray(accumulated[channel], dtype=float)
                if acc_data.ndim == 2 and acc_data.shape[1] > 0:
                    return np.nanmean(acc_data, axis=0)
        except Exception:
            pass
        try:
            return np.asarray(scan_data.data[channel], dtype=float).ravel()
        except Exception:
            return np.array([], dtype=float)

    @staticmethod
    def _extract_scan_axis_values(scan_data, n_points):
        n = int(max(0, n_points))
        if scan_data is None or n == 0:
            return np.array([], dtype=float)
        try:
            scan_range = scan_data.scan_range[0]
            return np.linspace(float(scan_range[0]), float(scan_range[1]), n, dtype=float)
        except Exception:
            return np.arange(n, dtype=float)

    @staticmethod
    def _extract_scan_axis_name(scan_data):
        if scan_data is None:
            return ""
        try:
            if len(scan_data.scan_axes) > 0:
                return str(scan_data.scan_axes[0])
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_scan_axis_unit(scan_data):
        if scan_data is None:
            return ""
        try:
            axis_name = scan_data.scan_axes[0]
            return str(scan_data.axes_units.get(axis_name, ""))
        except Exception:
            return ""

    @staticmethod
    def _extract_fit_values(fit_tuple):
        fit_center = np.nan
        fit_center_1 = np.nan
        fit_center_2 = np.nan
        fit_r2 = np.nan
        if fit_tuple is None:
            return fit_center, fit_center_1, fit_center_2, fit_r2

        if isinstance(fit_tuple, (tuple, list)) and len(fit_tuple) >= 2:
            fit_result = fit_tuple[1]
        else:
            fit_result = None

        if fit_result is None:
            return fit_center, fit_center_1, fit_center_2, fit_r2

        try:
            fit_r2 = float(fit_result.rsquared)
        except Exception:
            fit_r2 = np.nan

        params = getattr(fit_result, "params", {})
        if "center" in params:
            fit_center = float(params["center"].value)
        if "center_1" in params:
            fit_center_1 = float(params["center_1"].value)
            fit_center = fit_center_1
        if "center_2" in params:
            fit_center_2 = float(params["center_2"].value)
        return fit_center, fit_center_1, fit_center_2, fit_r2

    def _safe_get_current_field(self):
        try:
            return np.asarray(self._magnet_hw.get_field(), dtype=float)
        except Exception:
            self.log.exception("Could not read current magnet field.")
            return np.array([np.nan, np.nan, np.nan], dtype=float)

    def _safe_get_ramping_state(self):
        try:
            return list(self._magnet_hw.get_ramping_state())
        except Exception:
            return []

    @staticmethod
    def _cartesian_to_spherical(cartesian):
        x, y, z = np.asarray(cartesian, dtype=float)
        radius = float(np.sqrt(x * x + y * y + z * z))
        if not np.isfinite(radius) or radius == 0.0:
            return np.array([0.0, 0.0, 0.0], dtype=float)
        theta = float(np.degrees(np.arccos(np.clip(z / radius, -1.0, 1.0))))
        phi = float(np.degrees(np.arctan2(y, x)))
        if phi < 0:
            phi += 360.0
        return np.array([radius, theta, phi], dtype=float)

    def _sanitize_settings(self, settings):
        defaults = self.get_default_settings()
        merged = defaults if not isinstance(settings, dict) else {**defaults, **settings}

        plane = str(merged.get("plane", "XY")).upper()
        if plane not in ("XY", "XZ", "YZ"):
            plane = "XY"

        steps = int(merged.get("steps", 121))
        steps = max(2, steps)
        amplitude = float(merged.get("amplitude_t", 0.2))
        amplitude = max(0.0, amplitude)

        start = float(merged.get("start_angle_deg", 0.0))
        stop = float(merged.get("stop_angle_deg", 360.0))
        if np.isclose(start, stop):
            stop = start + 360.0

        sanitized = {
            "plane": plane,
            "amplitude_t": amplitude,
            "steps": steps,
            "start_angle_deg": start,
            "stop_angle_deg": stop,
            "bx_offset_t": float(merged.get("bx_offset_t", 0.0)),
            "by_offset_t": float(merged.get("by_offset_t", 0.0)),
            "bz_offset_t": float(merged.get("bz_offset_t", 0.0)),
            "fit_config": str(merged.get("fit_config", self._default_fit_config)),
            "fit_channel": str(merged.get("fit_channel", self._default_fit_channel)).strip(),
            "fit_averaged": bool(merged.get("fit_averaged", False)),
            "do_fit": bool(merged.get("do_fit", True)),
            "ple_repeats": max(1, int(merged.get("ple_repeats", self._default_ple_repeats))),
            "save_each_ple_scan": bool(merged.get("save_each_ple_scan", False)),
            "auto_save": bool(merged.get("auto_save", False)),
            "save_last_ple": bool(merged.get("save_last_ple", True)),
            "tag": str(merged.get("tag", "")).strip(),
            "root_dir": merged.get("root_dir", None),
            "scan_axis": str(merged.get("scan_axis", "")).strip(),
        }
        return sanitized

    def _generate_targets(self, settings):
        start = float(settings["start_angle_deg"])
        stop = float(settings["stop_angle_deg"])
        steps = int(settings["steps"])
        span = stop - start
        full_circle = np.isclose(np.mod(abs(span), 360.0), 0.0)
        angles_deg = np.linspace(start, stop, steps, endpoint=not full_circle, dtype=float)
        angles_rad = np.radians(angles_deg)

        b_amp = float(settings["amplitude_t"])
        bx_off = float(settings["bx_offset_t"])
        by_off = float(settings["by_offset_t"])
        bz_off = float(settings["bz_offset_t"])

        if settings["plane"] == "XY":
            bx = bx_off + b_amp * np.cos(angles_rad)
            by = by_off + b_amp * np.sin(angles_rad)
            bz = np.full(steps, bz_off, dtype=float)
        elif settings["plane"] == "XZ":
            bx = bx_off + b_amp * np.sin(angles_rad)
            by = np.full(steps, by_off, dtype=float)
            bz = bz_off + b_amp * np.cos(angles_rad)
        else:  # YZ
            bx = np.full(steps, bx_off, dtype=float)
            by = by_off + b_amp * np.sin(angles_rad)
            bz = bz_off + b_amp * np.cos(angles_rad)

        return np.column_stack((bx, by, bz)), angles_deg

    def _build_metadata(self):
        metadata = dict(self._settings)
        metadata["module"] = "BFieldSweepLogic"
        metadata["points_acquired"] = len(self._results)
        metadata["scan_axes"] = tuple(self._scan_axes)
        metadata["started_at"] = (
            None if self._sweep_started_at is None else self._sweep_started_at.isoformat()
        )
        metadata["saved_at"] = dt.datetime.now().isoformat()
        return metadata

    def _result_payload(self):
        return {
            "running": bool(self._running),
            "settings": dict(self._settings),
            "angles_deg": self._angles_deg.copy(),
            "results": [dict(item) for item in self._results],
            "current_index": int(self._point_index),
            "total_points": int(len(self._target_points)),
        }

    def _progress_payload(self, stage, ramping_state=None):
        target_field = self._current_target.copy()
        target_spherical = self._cartesian_to_spherical(target_field)
        total_points = int(len(self._target_points))
        if total_points > 0:
            index = int(min(max(self._point_index, 0), total_points - 1))
        else:
            index = 0
        return {
            "stage": stage,
            "index": index,
            "total": total_points,
            "angle_deg": float(
                self._angles_deg[self._point_index]
                if 0 <= self._point_index < len(self._angles_deg)
                else np.nan
            ),
            "target_field_t": target_field,
            "target_spherical": target_spherical,
            "ramping_state": [] if ramping_state is None else list(ramping_state),
        }
