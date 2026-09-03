# -*- coding: utf-8 -*-
"""
SSR analysis methods for pulsed measurements.
"""

import math
import numpy as np

from qudi.logic.pulsed.pulse_analyzer import PulseAnalyzerBase


class SnVSSRAnalyzer(PulseAnalyzerBase):
    """Pulse analyzer methods for SnV-style single-shot readout."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @staticmethod
    def _normal_cdf(x, mean, sigma):
        if sigma <= 0:
            return float(x >= mean)
        z_value = (float(x) - float(mean)) / (math.sqrt(2.0) * float(sigma))
        return 0.5 * (1.0 + math.erf(z_value))

    def analyse_snv_ssr(self, laser_data, signal_start=1.0e-6, signal_end=2.0e-6,
                        norm_start=0.0, norm_end=1.0e-6, crc_threshold=5.0,
                        ssr_threshold=2.0, bright_state_if_above=True, invalid_result=np.nan,
                        sequence_stride=3, crc_index=0, readout_index=2,
                        output_state='dark'):
        """
        Assign SSR probabilities with CRC pre-selection.

        This method expects repeating pulse triplets per shot by default:
        CRC -> Init -> Readout. The assignment can be changed with
        `sequence_stride`, `crc_index` and `readout_index`.

        The existing pulsed GUI windows are reused as:
        - `norm_start`/`norm_end` on the CRC pulse.
        - `signal_start`/`signal_end` on the readout pulse.

        Returns per-shot probabilities for the selected output state:
        - `output_state='dark'`: dark-state probability
        - `output_state='bright'`: bright-state probability
        - `invalid_result` for CRC-rejected shots and non-readout pulses
        """
        laser_data = np.asarray(laser_data)
        if laser_data.ndim < 2:
            laser_data = np.atleast_2d(laser_data)

        num_of_lasers = laser_data.shape[0]
        num_bins = laser_data.shape[1] if laser_data.ndim > 1 else 0
        bin_width = self.fast_counter_settings.get('bin_width')

        if not isinstance(bin_width, float):
            return np.zeros(num_of_lasers), np.zeros(num_of_lasers)

        try:
            invalid_value = float(invalid_result)
        except (TypeError, ValueError):
            invalid_value = np.nan

        probabilities = np.full(num_of_lasers, invalid_value, dtype=float)
        errors = np.zeros(num_of_lasers, dtype=float)

        stride = max(1, int(sequence_stride))
        crc_index_int = int(crc_index)
        readout_pos = int(readout_index) % stride
        output_state = str(output_state).strip().lower()
        if output_state not in ('dark', 'bright'):
            output_state = 'dark'

        def integrate_rows(rows, start_s, end_s):
            start_bin = int(round(start_s / bin_width))
            end_bin = int(round(end_s / bin_width))
            if end_bin < start_bin:
                start_bin, end_bin = end_bin, start_bin

            start_bin = min(max(start_bin, 0), num_bins)
            end_bin = min(max(end_bin, start_bin), num_bins)
            if end_bin <= start_bin or rows.size == 0:
                return np.zeros(rows.size, dtype=float)
            return np.sum(laser_data[rows, start_bin:end_bin], axis=1, dtype=float)

        complete_shots = num_of_lasers // stride
        if complete_shots < 1:
            self.last_analysis_result = {
                'ssr_enabled': True,
                'output_state': output_state,
                'valid_shots': 0,
                'total_shots': 0,
                'valid_fraction': 0.0,
                'fidelity': np.nan,
                'bright_state_if_above': bool(bright_state_if_above),
                'histogram_edges': list(),
                'histogram_bright': list(),
                'histogram_dark': list()
            }
            return probabilities, errors

        shot_offsets = np.arange(complete_shots, dtype=int) * stride
        
        if crc_index_int < 0:
            valid = np.ones(complete_shots, dtype=bool)
            crc_counts = np.zeros(complete_shots, dtype=float)
        else:
            crc_pos = crc_index_int % stride
            crc_rows = shot_offsets + crc_pos
            # 1. CRC pre-selection
            crc_counts = integrate_rows(crc_rows, norm_start, norm_end)
            valid = crc_counts >= float(crc_threshold)

        readout_rows = shot_offsets + readout_pos
        ssr_counts = integrate_rows(readout_rows, signal_start, signal_end)
        
        bright = ssr_counts > float(ssr_threshold) if bright_state_if_above else ssr_counts < float(ssr_threshold)
        bright_prob = np.full(complete_shots, np.nan, dtype=float)

        valid_bright_counts = ssr_counts[valid & bright]
        valid_dark_counts = ssr_counts[valid & ~bright]
        threshold = float(ssr_threshold)

        bright_mean_counts = np.nan
        dark_mean_counts = np.nan
        fidelity = np.nan

        # Estimate cluster overlap to report a readout-fidelity proxy from the current dataset.
        if valid_bright_counts.size > 0 and valid_dark_counts.size > 0:
            bright_mean_counts = float(np.mean(valid_bright_counts))
            dark_mean_counts = float(np.mean(valid_dark_counts))

            if ((bright_state_if_above and bright_mean_counts > dark_mean_counts) or
                    (not bright_state_if_above and bright_mean_counts < dark_mean_counts)):
                sigma_bright = max(math.sqrt(abs(bright_mean_counts)), 1.0)
                sigma_dark = max(math.sqrt(abs(dark_mean_counts)), 1.0)

                counts_valid = ssr_counts[valid].astype(float)
                log_prob_bright = (
                    -0.5 * ((counts_valid - bright_mean_counts) / sigma_bright) ** 2
                    - math.log(sigma_bright)
                )
                log_prob_dark = (
                    -0.5 * ((counts_valid - dark_mean_counts) / sigma_dark) ** 2
                    - math.log(sigma_dark)
                )
                max_log = np.maximum(log_prob_bright, log_prob_dark)
                prob_bright_valid = np.exp(log_prob_bright - max_log)
                prob_dark_valid = np.exp(log_prob_dark - max_log)
                bright_prob[valid] = prob_bright_valid / (prob_bright_valid + prob_dark_valid)

                if bright_state_if_above:
                    error_bright = self._normal_cdf(threshold, bright_mean_counts, sigma_bright)
                    error_dark = 1.0 - self._normal_cdf(threshold, dark_mean_counts, sigma_dark)
                else:
                    error_bright = 1.0 - self._normal_cdf(threshold, bright_mean_counts, sigma_bright)
                    error_dark = self._normal_cdf(threshold, dark_mean_counts, sigma_dark)
                fidelity = 1.0 - 0.5 * (error_bright + error_dark)

        if np.isnan(bright_prob[valid]).any():
            bright_prob[valid] = bright[valid].astype(float)

        output_prob = bright_prob if output_state == 'bright' else 1.0 - bright_prob
        probabilities[readout_rows[valid]] = output_prob[valid]
        errors[readout_rows[valid]] = np.sqrt(output_prob[valid] * (1.0 - output_prob[valid]))

        histogram_edges = np.array([], dtype=float)
        histogram_bright = np.array([], dtype=float)
        histogram_dark = np.array([], dtype=float)
        valid_counts = ssr_counts[valid]
        if valid_counts.size > 0:
            cmin = float(np.min(valid_counts))
            cmax = float(np.max(valid_counts))
            if np.isclose(cmax, cmin):
                histogram_edges = np.array([cmin - 0.5, cmax + 0.5], dtype=float)
            else:
                num_bins = int(np.clip(np.sqrt(valid_counts.size) * 2, 16, 80))
                histogram_edges = np.linspace(cmin, cmax, num_bins + 1, dtype=float)
            histogram_bright, _ = np.histogram(valid_bright_counts, bins=histogram_edges)
            histogram_dark, _ = np.histogram(valid_dark_counts, bins=histogram_edges)

        self.last_analysis_result = {
            'ssr_enabled': True,
            'output_state': output_state,
            'valid_shots': int(np.count_nonzero(valid)),
            'total_shots': int(complete_shots),
            'valid_fraction': float(np.count_nonzero(valid) / complete_shots),
            'fidelity': float(fidelity) if np.isfinite(fidelity) else np.nan,
            'crc_threshold': float(crc_threshold),
            'ssr_threshold': threshold,
            'bright_state_if_above': bool(bright_state_if_above),
            'bright_mean_counts': bright_mean_counts,
            'dark_mean_counts': dark_mean_counts,
            'histogram_edges': histogram_edges.tolist(),
            'histogram_bright': histogram_bright.astype(float).tolist(),
            'histogram_dark': histogram_dark.astype(float).tolist()
        }
        return probabilities, errors
