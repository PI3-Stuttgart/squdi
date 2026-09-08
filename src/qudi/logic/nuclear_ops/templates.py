"""Editable experiment presets; no implicit lab calibration values."""
def experiment_template(recipe):
    axes = {
        "optical_rabi": ("optical_duration_ns", 16, 800, "ns"),
        "optical_power_rabi": ("optical_voltage", 0.0, 0.2, "V"),
        "ple_iterator": ("laser_frequency_voltage", -0.1, 0.1, "V"),
        "initialization_calibration": ("electron_init_duration_ns", 40, 4000, "ns"),
        "field_alignment": ("B_theta", 0, 20, "deg"),
        "spin_photon_correlation": ("sweeps", 0, 100, ""),
        "nuclear_rabi": ("pulse_length", 40, 4000, "ns"),
        "ramsey": ("tau", 40, 4000, "ns"),
        "hahn_echo": ("tau", 40, 20000, "ns"),
        "t1": ("readout_delay", 40, 100000, "ns"),
        "pulsed_odmr": ("MW_f", 190000000, 210000000, "Hz"),
        "ssr_calibration": ("sweeps", 0, 100, ""),
    }
    axis, start, stop, unit = axes[recipe]
    values = [int(round((start + (stop-start)*i/40)/4)*4) if unit == "ns" else (start+(stop-start)*i/40 if unit == "V" else int(start+(stop-start)*i/40)) for i in range(41)]
    result = {
        "recipe": recipe, "name": recipe.replace("_", " ").title(),
        "scan_axes": [{"name": "repeat", "values": list(range(8)), "execution": "recompile"},
                      {"name": axis, "values": values, "unit": unit, "execution": "host" if recipe == "field_alignment" else "qua"}],
        "parameters": {"integrations": 20, "max_time_tags": 128, "fit_axis": axis},
        "readout": [{"kind": "ssr", "threshold_ref": "ssr_e1", "output_name": "result_counts"}],
        "threshold_profile": "default", "execution": {"save_raw_events": True},
    }
    if recipe == "field_alignment":
        result["parameters"]["B_amp"] = 0.0
    if recipe == "ssr_calibration":
        result["scan_axes"][0] = {"name": "init_state", "values": ["e1", "e2"], "execution": "recompile"}
    return result
