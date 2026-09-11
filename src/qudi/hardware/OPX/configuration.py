import numpy as np
from qualang_tools.units import unit

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


def round_to_nearest_4(x):
    return ((x + 3) // 4) * 4


#############
# VARIABLES #
#############
qop_ip = "192.168.1.6"
host = 80
cluster_name = "OPX_Stuttgart"
qop_port = None  # Write the QOP port if version < QOP220
octave_config = None


### Microwave ###
# Delays
MW_IQ_DELAY = (1_015 - 200) * u.ns
MW_SWITCH_TTL_DELAY = MW_IQ_DELAY + 75 * u.ns
# Buffers
MW_SWITCH_TTL_BUFFER = 150 * u.ns
# Mixer
SMIQ_LO_FREQ = 3.9 * u.GHz
IQ_FREQ = 0 * u.MHz

### Laser 520 ###
# Delays
LASER_520_AOM_TTL_DELAY = 235 * u.ns
LASER_520_AOM_MOD_DELAY = 0 * u.ns
LASER_520_TTL_DELAY = 0 * u.ns

### Laser 450 ###
# Delays
LASER_450_TTL_DELAY = 580 * u.ns
LASER_450_ATT_DELAY = 0 * u.ns

### Laser 620 ###
# Delays
LASER_620_AOM_TTL_DELAY = 150 * u.ns
LASER_620_AOM_MOD_DELAY = 0 * u.ns

### Laser 620 det ###
# Delays
LASER_620_DET_AOM_TTL_DELAY = 248 * u.ns
LASER_620_DET_AOM_MOD_DELAY = 0 * u.ns

### Laser 620 pi ###
# Delays
LASER_620_PI_AOM_TTL_DELAY = 0 * u.ns
LASER_620_PI_AOM_MOD_DELAY = 0 * u.ns
LASER_620_PI_PPG_TTL_DELAY = 554 * u.ns

### TRIGGER TIMETAGGER ###
TIMETAGGER_COUNTER_DELAY = 817 * u.ns

### OPX TIMETAGGING ###
SPCM_1_DELAY = TIMETAGGER_COUNTER_DELAY * u.ns
SPCM_2_DELAY = TIMETAGGER_COUNTER_DELAY * u.ns


config = {
    "version": 1,
    "controllers": {
        "con1": {
            "analog_outputs": {
                1: {"offset": 0, "delay": MW_IQ_DELAY},  # MW I
                2: {"offset": 0, "delay": MW_IQ_DELAY},  # MW Q
                3: {"offset": 0, "delay": 0 * u.ns},  # Not used
                4: {"offset": 0, "delay": 0 * u.ns},  # Freq scanner Laser 620
                5: {"offset": 0, "delay": LASER_620_DET_AOM_MOD_DELAY},  # Laser 620 det AOM MOD
                6: {"offset": 0, "delay": LASER_620_PI_AOM_MOD_DELAY},  # Laser 620 pi AOM MOD
                7: {"offset": 0, "delay": LASER_450_ATT_DELAY},  # Laser 450 Attenuator
                8: {"offset": 0, "delay": LASER_520_AOM_MOD_DELAY},  # Laser 520 AOM MOD
                9: {"offset": 0, "delay": LASER_620_AOM_MOD_DELAY},  # Laser 620 AOM 1 MOD
                10: {"offset": 0, "delay": LASER_620_AOM_MOD_DELAY},  # Laser 620 AOM 2 MOD
            },
            "digital_outputs": {
                1: {},  # MW switch TTL
                2: {"inverted": True},  # Laser 620 det AOM TTL
                3: {},  # Gate Trigger - TT channel 5.
                4: {},  # Memory Trigger - TT channle 4
                5: {},  # Laser 620 pi PPG trigger
                6: {},  # Laser 520 TTL
                7: {},  # Laser 450 TTL
                8: {},  # Laser 520 AOM TTL
                9: {},  # Laser 620 AOM TTL
                10: {},  # Laser 620 pi AOM TTL
            },
            "analog_inputs": {
                1: {"offset": 0, "gain_db": -3},  # SPCM 1
                2: {"offset": 0, "gain_db": -3},  # SPCM 2
            },
        }
    },
    "elements": {
        "MW": {  # MW
            "mixInputs": {
                "I": ("con1", 1),
                "Q": ("con1", 2),
                "lo_frequency": SMIQ_LO_FREQ,
                "mixer": "mixer_MW",
            },
            "intermediate_frequency": IQ_FREQ,
            "digitalInputs": {
                "switch": {
                    "port": ("con1", 1),
                    "delay": MW_SWITCH_TTL_DELAY,
                    "buffer": MW_SWITCH_TTL_BUFFER,
                },
            },
            "operations": {
                "x": "mw_x",
                "-x": "mw_minus_x",
                "y": "mw_y",
                "-y": "mw_minus_y",
                "switch": "mw_switch_pulse",
            },
        },
        "Gate_Trigger": {
            "digitalInputs": {
                "trigger": {
                    "port": ("con1", 3),
                    "delay": TIMETAGGER_COUNTER_DELAY,
                    "buffer": 0,
                },
            },
            "operations": {
                "trigit": "DO_pulse",
            },
        },
        "Memory_Trigger": {
            "digitalInputs": {
                "trigger": {
                    "port": ("con1", 4),
                    "delay": TIMETAGGER_COUNTER_DELAY,
                    "buffer": 0,
                },
            },
            "operations": {
                "trigit": "DO_pulse",
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
                "trigit": "DO_pulse",
            },
        },
        "Laser_620_pi": {
            "singleInput": {
                "port": ("con1", 6),
            },
            "digitalInputs": {
                "ppg": {
                    "port": ("con1", 5),
                    "delay": LASER_620_PI_PPG_TTL_DELAY,
                    "buffer": 0,
                },
                "AOM_620_pi": {
                    "port": ("con1", 10),
                    "delay": LASER_620_PI_AOM_TTL_DELAY,
                    "buffer": 0 * u.ns,
                },
            },
            "operations": {
                "power": "Laser_power",
                "active": "Laser_TTL",
                "pulse": "Laser_pulse",
            },
        },
        "Laser_620": {
            "multipleInputs": {"inputs": {"AOM_1": ("con1", 9), "AOM_2": ("con1", 10)}},
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 9),
                    "delay": LASER_620_AOM_TTL_DELAY,
                    "buffer": 0,
                },
            },
            "operations": {
                "power": "Laser_power",
                "active": "Laser_TTL",
                "pulse": "Laser_pulse",
            },
        },
        "Laser_620_det": {
            "singleInput": {
                "port": ("con1", 5),
            },
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 2),
                    "delay": LASER_620_DET_AOM_TTL_DELAY,
                    "buffer": 0,
                },
            },
            "operations": {
                "power": "Laser_power",
                "active": "Laser_TTL",
                "pulse": "Laser_pulse",
            },
        },
        "Laser_520": {
            "singleInput": {
                "port": ("con1", 8),
            },
            "digitalInputs": {
                "AOM": {
                    "port": ("con1", 8),
                    "delay": LASER_520_AOM_TTL_DELAY,
                    "buffer": 0,
                },
                "Laser": {
                    "port": ("con1", 6),
                    "delay": LASER_520_TTL_DELAY,
                    "buffer": 0,
                },
            },
            "operations": {
                "power": "Laser_power",
                "active": "Laser_TTL",
                "pulse": "Laser_pulse",
            },
        },
        "Laser_450": {
            "singleInput": {
                "port": ("con1", 7),
            },
            "digitalInputs": {
                "Laser": {
                    "port": ("con1", 7),
                    "delay": LASER_450_TTL_DELAY,
                    "buffer": 0,
                },
            },
            "operations": {
                "power": "Laser_power",
                "active": "Laser_TTL",
                "pulse": "Laser_pulse",
            },
        },
        "Laser_620_freq": {
            "singleInput": {
                "port": ("con1", 4),
            },
            "operations": {
                "power": "AO_pulse",
            },
        },
        "SPCM1": {
            "singleInput": {"port": ("con1", 1)},  # not used
            "operations": {
                "readout": "readout_pulse",
            },
            "outputs": {"out1": ("con1", 1)},
            "outputPulseParameters": {
                "signalThreshold": -200,  # ADC units
                "signalPolarity": "Below",
                "derivativeThreshold": -82,
                "derivativePolarity": "Below",
            },
            "time_of_flight": round_to_nearest_4(SPCM_1_DELAY),
            "smearing": 0,
        },
        "SPCM2": {
            "singleInput": {"port": ("con1", 1)},  # not used
            "operations": {
                "readout": "readout_pulse",
            },
            "outputs": {"out1": ("con1", 2)},
            "outputPulseParameters": {
                "signalThreshold": -200,  # ADC units
                "signalPolarity": "Below",
                "derivativeThreshold": -82,
                "derivativePolarity": "Below",
            },
            "time_of_flight": round_to_nearest_4(SPCM_2_DELAY),  # in ns, dividable by 4
            "smearing": 0,
        },
    },
    "pulses": {
        "mw_const_pulse": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {"I": "cw_wf", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "mw_switch_pulse": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {"I": "zero_wf", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "mw_x": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {"I": "cw_wf", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "mw_minus_x": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {"I": "cw_wf_minus", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "mw_y": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {"I": "zero_wf", "Q": "cw_wf"},
            "digital_marker": "ON",
        },
        "mw_minus_y": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {"I": "zero_wf", "Q": "cw_wf_minus"},
            "digital_marker": "ON",
        },
        # AOM Pulses
        "Laser_RF_pulse": {
            "operation": "control",
            "length": 200 * u.ns,  # in ns
            "waveforms": {"single": "cw_wf"},
        },
        "Laser_TTL": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {
                "single": "zero_wf",
            },
            "digital_marker": "ON",
        },
        "Laser_power": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {
                "single": "cw_wf",
            },
            "digital_marker": "OFF",
        },
        "Laser_pulse": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {
                "single": "cw_wf",
            },
            "digital_marker": "ON",
        },
        "DO_pulse": {
            "operation": "control",
            "length": 200 * u.ns,
            "digital_marker": "ON",
        },
        "AO_pulse": {
            "operation": "control",
            "length": 200 * u.ns,
            "waveforms": {
                "single": "cw_wf",
            },
        },
        "readout_pulse": {
            "operation": "measurement",
            "length": 500 * u.ns,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
    },
    "waveforms": {
        "cw_wf": {"type": "constant", "sample": 0.5},
        "cw_wf_minus": {"type": "constant", "sample": -0.5},
        "zero_wf": {"type": "constant", "sample": 0.0},
    },
    "digital_waveforms": {
        "ON": {"samples": [(1, 0)]},  # [(on/off, ns)]
        "OFF": {"samples": [(0, 0)]},  # [(on/off, ns)]
    },
    "mixers": {
        "mixer_MW": [
            {
                "intermediate_frequency": IQ_FREQ,
                "lo_frequency": SMIQ_LO_FREQ,
                "correction": IQ_imbalance(0.0, 0.0),
            },
        ],
    },
}
