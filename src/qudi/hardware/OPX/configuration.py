import numpy as np
from qualang_tools.units import unit
from qualang_tools.plot import interrupt_on_close
from qualang_tools.results import progress_counter, fetching_tool
from qualang_tools.loops import from_array

#######################
# AUXILIARY FUNCTIONS #
#######################
u = unit(coerce_to_integer=True)


# IQ imbalance matrix
def IQ_imbalance(g, phi):
    """
    Creates the correction matrix for the mixer imbalance caused by the gain and phase imbalances, more information can
    be seen here:
    https://docs.qualang.io/libs/examples/mixer-calibration/#non-ideal-mixer
    :param g: relative gain imbalance between the 'I' & 'Q' ports. (unit-less), set to 0 for no gain imbalance.
    :param phi: relative phase imbalance between the 'I' & 'Q' ports (radians), set to 0 for no phase imbalance.
    """
    c = np.cos(phi)
    s = np.sin(phi)
    N = 1 / ((1 - g**2) * (2 * c**2 - 1))
    return [float(N * x) for x in [(1 - g) * c, (1 + g) * s, (1 - g) * s, (1 + g) * c]]


#############
# VARIABLES #
#############
qop_ip = "192.168.1.6"  # Write the OPX IP address
host = 80
cluster_name = "OPX_Stuttgart"  # Write your cluster_name if version >= QOP220
qop_port = None  # Write the QOP port if version < QOP220
# Set octave_config to None if no octave are present
octave_config = None

# Frequencies
NV_IF_freq = 108.2180 * u.MHz
NV_LO_freq = 2.87 * u.GHz

# Pulses lengths
initialization_len_green = 3_000 * u.ns
meas_len_1 = 500 * u.ns  # 500
long_meas_len_1 = 5_000 * u.ns

initialization_len_2 = 3000 * u.ns
meas_len_2 = 500 * u.ns
long_meas_len_2 = 5_000 * u.ns
initialization_len_laser: float = 3_000 * u.ns

AOM_power_len = 80 * u.ns

# Relaxation time from the metastable state to the ground state after during initialization
relaxation_time = 300 * u.ns
wait_for_initialization = 5 * relaxation_time

# MW parameters
mw_amp_NV = 0.2  # in units of volts
mw_len_NV = 1000 * u.ns

x180_amp_NV = 0.4  # in units of volts
x180_len_NV = 32  # in units of ns # 32

x90_amp_NV = x180_amp_NV / 2  # in units of volts
x90_len_NV = x180_len_NV  # in units of ns

# RF parameters
rf_frequency = 10 * u.MHz
rf_amp = 0.1
rf_length = 1000

# Readout parameters
signal_threshold_1 = -1_000  # ADC untis, to convert to volts divide by 4096 (12 bit ADC)
signal_threshold_2 = -1_000  # ADC untis, to convert to volts divide by 4096 (12 bit ADC)

# PLE parameters
ple_step_length_red = 1 * u.us

# Delays
detection_delay_1 = 36 * u.ns  # 144
detection_delay_2 = 80 * u.ns
# Lasers
laser_delay_520 = 0 * u.ns
laser_delay_450 = 0 * u.ns

laser_power_delay_450 = 0 * u.ns

LaserScanner_delay = 0 * u.ns
# AOMs
AOM_delay_520 = 120 * u.ns
AOM_delay_575 = 0 * u.ns
AOM_delay_620 = 0 * u.ns

# AOM / EOM 620 pi path
AOM_620_pi_delay = 110 * u.ns
PPG_delay = 382 * u.ns

AOM_power_delay_520 = 0 * u.ns
AOM_power_delay_575 = 0 * u.ns
AOM_power_delay_620 = 0 * u.ns
# MW/RF
mw_delay = 0 * u.ns
rf_delay = 0 * u.ns

counter_delay = 600 * u.ns  # delay was 600 * u.ns changed it to test


wait_between_runs = 1500


config = {
    "version": 1,
    "controllers": {
        "con1": {
            "analog_outputs": {
                1: {"offset": 0.0, "delay": mw_delay},  # NV I
                2: {"offset": 0.0, "delay": mw_delay},  # NV Q
                3: {"offset": 0.0, "delay": rf_delay},  # RF
                4: {"offset": 0.0, "delay": LaserScanner_delay},  # Piezo 620 nm laser
                6: {
                    "offset": 0.0,
                    "delay": AOM_power_delay_620,
                },  # AOM Laser 620 nm (Orange) free Space
                7: {
                    "offset": 0.0,
                    "delay": laser_power_delay_450,
                },  #  Attenuator (power) Laser 450 nm (Blue)
                8: {
                    "offset": 0.0,
                    "delay": AOM_power_delay_520,
                },  # AOM Laser 520 (Green)
                9: {
                    "offset": 0.0,
                    "delay": AOM_power_delay_620,
                },  # AOM Laser 620 nm (Orange)
                10: {
                    "offset": 0.0,
                    "delay": AOM_power_delay_620,
                },  # AOM Laser 620 nm (Orange)
            },
            "digital_outputs": {
                1: {},  # MW switch
                2: {},  # For now: trigger TT attodry # Master - slave trigger RESERVED for SETUP#2.
                3: {},  # Gate Trigger - to the TT ...channel 5 on the TT.
                4: {},  # Memory Trigger - to the TT ... channel 4 on the TT
                5: {},  # PPG trigger
                6: {},  # Laser 520 nm (Green)
                7: {},  # Laser 450 nm (Blue)
                8: {},  # AOM Laser 520 nm (Green)
                9: {},  # AOM Laser 620 nm (Orange)
                10: {},  # AOM Laser 620 nm (Orange) for EOM path
            },
            "analog_inputs": {
                1: {"offset": 0, "gain_db": -3},  # SPCM1
                2: {"offset": 0, "gain_db": -3},  # SPCM2
            },
        }
    },
    "elements": {
        "NV": {
            "mixInputs": {
                "I": ("con1", 1),
                "Q": ("con1", 2),
                "lo_frequency": NV_LO_freq,
                "mixer": "mixer_NV",
            },
            "intermediate_frequency": NV_IF_freq,
            "digitalInputs": {
                "switch": {
                    "port": ("con1", 1),
                    "delay": 113 * u.ns,
                    "buffer": 25 * u.ns,
                },
            },
            "operations": {
                "cw": "const_pulse",
                "x180": "x180_pulse",
                "x90": "x90_pulse",
                "-x90": "-x90_pulse",
                "-y90": "-y90_pulse",
                "y90": "y90_pulse",
                "y180": "y180_pulse",
            },
        },
        "RF": {
            "singleInput": {"port": ("con1", 3)},
            "intermediate_frequency": rf_frequency,
            "operations": {
                "const": "const_pulse_single",
                # "x180": "x180_pulse",
            },
        },
        "Laser_450": {
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 7),
                    "delay": laser_delay_450,
                    "buffer": 0,
                },
            },
            "operations": {
                "active": "laser_ON",
            },
        },
        "Gate_Trigger": {
            "digitalInputs": {
                "trigger": {
                    "port": ("con1", 3),
                    "delay": counter_delay,
                    "buffer": 0,
                },
            },
            "operations": {
                "trigit": "laser_ON",
            },
        },
        "Memory_Trigger": {
            "digitalInputs": {
                "trigger": {
                    "port": ("con1", 4),
                    "delay": counter_delay,
                    "buffer": 0,
                },
            },
            "operations": {
                "trigit": "laser_ON",
            },
        },
        "TT_attodry_trigger": {
            "digitalInputs": {
                "trigger": {
                    "port": ("con1", 2),
                    "delay": 0,
                    "buffer": 0,
                },
            },
            "operations": {
                "trigit": "laser_ON",
            },
        },
        "620_pi": {
            "digitalInputs": {
                "ppg": {
                    "port": ("con1", 5),
                    "delay": PPG_delay,  # 294
                    "buffer": 0,
                },
                "AOM_620_pi": {"port": ("con1", 10), "delay": AOM_620_pi_delay, "buffer": 0 * u.ns},
            },
            "operations": {
                "trigit": "TTL_only_digital",
                "active": "TTL_only_digital",
            },
        },
        "Laser_620_pi": {
            "singleInput": {
                "port": ("con1", 7),
            },
            "digitalInputs": {
                "ppg": {
                    "port": ("con1", 5),
                    "delay": PPG_delay,  # 294
                    "buffer": 0,
                },
                "AOM_620_pi": {"port": ("con1", 10), "delay": AOM_620_pi_delay, "buffer": 0 * u.ns},
            },
            "operations": {
                "power": "AOM_power",
                "active": "AOM_TTL",
                "pulse": "AOM_pulse",
            },
        },
        "Laser_620": {
            "multipleInputs": {"inputs": {"input1": ("con1", 9), "input2": ("con1", 10)}},
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 9),
                    "delay": AOM_delay_620,
                    "buffer": 0,
                },
            },
            "operations": {
                "power": "AOM_power",
                "active": "AOM_TTL",
                "pulse": "AOM_pulse",
            },
        },
        "Laser_520": {
            "singleInput": {
                "port": ("con1", 8),
            },
            "digitalInputs": {
                "AOM": {
                    "port": ("con1", 8),
                    "delay": AOM_delay_520,
                    "buffer": 0,
                },
                "Laser": {
                    "port": ("con1", 6),
                    "delay": AOM_delay_520,
                    "buffer": 0,
                },
            },
            "operations": {
                "power": "AOM_power",
                "active": "AOM_TTL",
                "pulse": "AOM_pulse",
            },
        },
        "Laser_620_freq": {
            "singleInput": {
                "port": ("con1", 4),
            },
            "operations": {
                "power": "piezo_offset_red",
            },
        },
        "SPCM1": {
            "singleInput": {"port": ("con1", 1)},  # not used
            # "digitalInputs": {  # for visualization in simulation
            #     "marker": {
            #         "port": ("con1", 1),
            #         "delay": detection_delay_1,
            #         "buffer": 0,
            #     },
            # },
            "operations": {
                "readout": "readout_pulse_1",
                "long_readout": "long_readout_pulse_1",
            },
            "outputs": {"out1": ("con1", 1)},
            "outputPulseParameters": {
                "signalThreshold": -200,  # ADC units
                "signalPolarity": "Below",
                "derivativeThreshold": -82,
                "derivativePolarity": "Below",
            },
            "time_of_flight": detection_delay_1,
            "smearing": 0,
        },
        "SPCM2": {
            "singleInput": {"port": ("con1", 1)},  # not used
            "digitalInputs": {  # for visualization in simulation
                "marker": {
                    "port": ("con1", 4),
                    "delay": detection_delay_2,
                    "buffer": 0,
                },
            },
            "operations": {
                "readout": "readout_pulse_2",
                "long_readout": "long_readout_pulse_2",
            },
            "outputs": {"out1": ("con1", 2)},
            "outputPulseParameters": {
                "signalThreshold": signal_threshold_2,  # ADC units
                "signalPolarity": "Below",
                "derivativeThreshold": -2_000,
                "derivativePolarity": "Above",
            },
            "time_of_flight": detection_delay_2,
            "smearing": 0,
        },
    },
    "pulses": {
        "const_pulse": {
            "operation": "control",
            "length": mw_len_NV,
            "waveforms": {"I": "cw_wf", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "x180_pulse": {
            "operation": "control",
            "length": x180_len_NV,
            "waveforms": {"I": "x180_wf", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "x90_pulse": {
            "operation": "control",
            "length": x90_len_NV,
            "waveforms": {"I": "x90_wf", "Q": "zero_wf"},
        },
        "-x90_pulse": {
            "operation": "control",
            "length": x90_len_NV,
            "waveforms": {"I": "minus_x90_wf", "Q": "zero_wf"},
        },
        "-y90_pulse": {
            "operation": "control",
            "length": x90_len_NV,
            "waveforms": {"I": "zero_wf", "Q": "minus_x90_wf"},
        },
        "y90_pulse": {
            "operation": "control",
            "length": x90_len_NV,
            "waveforms": {"I": "zero_wf", "Q": "x90_wf"},
        },
        "y180_pulse": {
            "operation": "control",
            "length": x180_len_NV,
            "waveforms": {"I": "zero_wf", "Q": "x180_wf"},
        },
        "const_pulse_single": {
            "operation": "control",
            "length": rf_length,  # in ns
            "waveforms": {"single": "rf_const_wf"},
        },
        # AOM Pulses
        "AOM_TTL": {
            "operation": "control",
            "length": initialization_len_laser,
            "waveforms": {
                "single": "zero_wf",
            },
            "digital_marker": "ON",
        },
        "TTL_only_digital": {
            "operation": "control",
            "length": initialization_len_laser,
            "digital_marker": "ON",
        },
        "AOM_power": {
            "operation": "control",
            "length": initialization_len_laser,
            "waveforms": {
                "single": "cw_aom",
            },
            "digital_marker": "OFF",
        },
        "AOM_pulse": {
            "operation": "control",
            "length": initialization_len_laser,
            "waveforms": {
                "single": "cw_aom",
            },
            "digital_marker": "ON",
        },
        "laser_ON": {
            "operation": "control",
            "length": initialization_len_laser,
            "digital_marker": "ON",
        },
        "readout_pulse_1": {
            "operation": "measurement",
            "length": meas_len_1,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
        "long_readout_pulse_1": {
            "operation": "measurement",
            "length": long_meas_len_1,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
        "readout_pulse_2": {
            "operation": "measurement",
            "length": meas_len_2,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
        "long_readout_pulse_2": {
            "operation": "measurement",
            "length": long_meas_len_2,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
        "piezo_offset_red": {
            "operation": "control",
            "length": ple_step_length_red,
            "waveforms": {
                "single": "const_piezo_offset",
            },
        },
    },
    "waveforms": {
        "cw_wf": {"type": "constant", "sample": mw_amp_NV},
        "rf_const_wf": {"type": "constant", "sample": rf_amp},
        "x180_wf": {"type": "constant", "sample": x180_amp_NV},
        "x90_wf": {"type": "constant", "sample": x90_amp_NV},
        "minus_x90_wf": {"type": "constant", "sample": -x90_amp_NV},
        "zero_wf": {"type": "constant", "sample": 0.0},
        "const_piezo_offset": {
            "type": "constant",
            "sample": 0.5,
        },  # Piezo offset puls for PLE
        "cw_aom": {
            "type": "constant",
            "sample": 0.5,
        },
    },
    "digital_waveforms": {
        "ON": {"samples": [(1, 0)]},  # [(on/off, ns)]
        "OFF": {"samples": [(0, 0)]},  # [(on/off, ns)]
    },
    "mixers": {
        "mixer_NV": [
            {
                "intermediate_frequency": NV_IF_freq,
                "lo_frequency": NV_LO_freq,
                "correction": IQ_imbalance(0.0, 0.0),
            },
        ],
    },
}
