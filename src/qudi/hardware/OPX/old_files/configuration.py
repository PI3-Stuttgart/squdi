import numpy as np


#######################
# AUXILIARY FUNCTIONS #
#######################


# IQ imbalance matrix
def IQ_imbalance(g, phi):
    """
    Creates the correction matrix for the mixer imbalance caused by the gain and phase imbalances, more information can
    be seen here:
    https://docs.qualang.io/libs/examples/mixer-calibration/#non-ideal-mixer

    :param g: relative gain imbalance between the I & Q ports (unit-less). Set to 0 for no gain imbalance.
    :param phi: relative phase imbalance between the I & Q ports (radians). Set to 0 for no phase imbalance.
    """
    c = np.cos(phi)
    s = np.sin(phi)
    N = 1 / ((1 - g**2) * (2 * c**2 - 1))
    return [float(N * x) for x in [(1 - g) * c, (1 + g) * s, (1 - g) * s, (1 + g) * c]]


def gauss(amplitude, mu, sigma, length):
    t = np.linspace(-length / 2, length / 2, length)
    gauss_wave = amplitude * np.exp(-((t - mu) ** 2) / (2 * sigma**2))
    substracted_gauss_wave = gauss_wave - gauss_wave[-1]
    return [float(x) for x in substracted_gauss_wave]


#############
# VARIABLES #
#############

qop_ip = "192.168.1.6"
host = 80

# Frequencies
# NV_IF1_freq = -67e6  # in units of Hz
# NV_IF2_freq = 350e6  # in units of Hz
NV_IF1_freq = 3e6
NV_IF2_freq = 0e6
NV_LO_freq = 2.870e9  # in units of Hz

# Pulses lengths
initialization_len = 3000  # in ns
orange_laser_len = 3e6
meas_len = 260  # in ns
meas_len_orange = int(3e6)
long_meas_len = 1e5  # in ns

# MW parameters
mw_amp_NV = 0.4  # in units of volts
mw_len_NV = 1000  # in units of ns

pi_amp_NV = 0.4  # in units of volts
pi_len_NV = 800  # in units of ns

pi_half_amp_NV = pi_amp_NV  # in units of volts
pi_half_len_NV = pi_len_NV / 2  # in units of ns

# Readout parameters
signal_threshold = -1000

# Delays
detection_delay = 144
mw_delay = 0
green_laser_delay = 0
orange_laser_delay = 0
red_laser_delay = 0

config = {
    "version": 1,
    "controllers": {
        "con1": {
            "type": "opx1",
            "analog_outputs": {
                1: {"offset": 0.0, "delay": mw_delay},  # NV I
                2: {"offset": 0.0, "delay": mw_delay},  # NV Q
                3: {"offset": 0.0, "delay": mw_delay},  # NV Q
                4: {"offset": 0.0, "delay": mw_delay},  # NV Q
            },
            "digital_outputs": {
                1: {},  # Photo diode - indicator
                2: {},  # AOM/green Laser
                3: {},  # AOM/orange Laser
                4: {},  # AOM/red Laser
                5: {},  #
                6: {},  # turn green on
            },
            "analog_inputs": {
                1: {"offset": 0, "gain_db": -3},  # SPCM
            },
        }
    },
    "elements": {
        "NV1": {
            "mixInputs": {
                "I": ("con1", 1),
                "Q": ("con1", 2),
                "lo_frequency": NV_LO_freq,
                "mixer": "mixer_NV1",
            },
            "intermediate_frequency": NV_IF1_freq,
            "operations": {
                "cw": "const_pulse",
                "pi": "x180_pulse",
                "pi_half": "x90_pulse",
            },
        },
        "NV2": {
            "mixInputs": {
                "I": ("con1", 3),
                "Q": ("con1", 4),
                "lo_frequency": NV_LO_freq,
                "mixer": "mixer_NV2",
            },
            "intermediate_frequency": NV_IF2_freq,
            "operations": {
                "cw": "const_pulse",
                "pi": "x180_pulse",
                "pi_half": "x90_pulse",
            },
        },
        "AOM_green": {
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 6),
                    "delay": green_laser_delay,
                    "buffer": 0,
                },
            },
            "operations": {
                "laser_ON": "laser_ON",
            },
        },
        "AOM_red": {
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 4),
                    "delay": red_laser_delay,
                    "buffer": 0,
                },
            },
            "operations": {
                "laser_ON": "laser_ON",
            },
        },
        "AOM_orange": {
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 3),
                    "delay": orange_laser_delay,
                    "buffer": 0,
                },
            },
            "operations": {
                "laser_ON": "laser_ON_orange",
            },
        },
        "SPCM": {
            "singleInput": {"port": ("con1", 1)},  # not used
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 1),
                    "delay": detection_delay,
                    "buffer": 0,
                },
            },
            "operations": {
                "readout": "readout_pulse",
                "readout_orange": "readout_orange_pulse",
                "long_readout": "long_readout_pulse",
            },
            "outputs": {"out1": ("con1", 1)},
            "outputPulseParameters": {
                "signalThreshold": signal_threshold,
                "signalPolarity": "Descending",
                "derivativeThreshold": 1023,
                "derivativePolarity": "Descending",
            },
            "time_of_flight": detection_delay,
            "smearing": 0,
        },
    },
    "pulses": {
        "const_pulse": {
            "operation": "control",
            "length": mw_len_NV,
            "waveforms": {"I": "cw_wf", "Q": "zero_wf"},
        },
        "x180_pulse": {
            "operation": "control",
            "length": pi_len_NV,
            "waveforms": {"I": "pi_wf", "Q": "zero_wf"},
        },
        "x90_pulse": {
            "operation": "control",
            "length": pi_half_len_NV,
            "waveforms": {"I": "pi_half_wf", "Q": "zero_wf"},
        },
        "laser_ON": {
            "operation": "control",
            "length": initialization_len,
            "digital_marker": "ON",
        },
        "laser_ON_orange": {
            "operation": "control",
            "length": orange_laser_len,
            "digital_marker": "ON",
        },
        "readout_pulse": {
            "operation": "measurement",
            "length": meas_len,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
        "readout_orange_pulse": {
            "operation": "measurement",
            "length": orange_laser_len,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
        "long_readout_pulse": {
            "operation": "measurement",
            "length": long_meas_len,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
    },
    "waveforms": {
        "cw_wf": {"type": "constant", "sample": mw_amp_NV},
        "pi_wf": {"type": "constant", "sample": pi_amp_NV},
        "pi_half_wf": {"type": "constant", "sample": pi_half_amp_NV},
        "zero_wf": {"type": "constant", "sample": 0.0},
    },
    "digital_waveforms": {
        "ON": {"samples": [(1, 0)]},  # [(on/off, ns)]
        "OFF": {"samples": [(0, 0)]},  # [(on/off, ns)]
    },
    "mixers": {
        "mixer_NV1": [
            {
                "intermediate_frequency": NV_IF1_freq,
                "lo_frequency": NV_LO_freq,
                "correction": IQ_imbalance(0.0, 0.0),
            },
        ],
        "mixer_NV2": [
            {
                "intermediate_frequency": NV_IF2_freq,
                "lo_frequency": NV_LO_freq,
                "correction": IQ_imbalance(0.0, 0.0),
            },
        ],
    },
}
