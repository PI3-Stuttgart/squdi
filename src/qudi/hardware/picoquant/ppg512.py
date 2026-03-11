# pip install pyserial
import serial
import csv
import numpy as np
from qudi.hardware.picoquant.crc import get_chck_summ  # file supplied by picoquant
import time
import matplotlib.pyplot as plt
import os

from qudi.core.module import Base
from qudi.core.configoption import ConfigOption


class waveform_generation:
    def __init__(self):
        self.path_to_folder = os.path.dirname(os.path.abspath(__file__))

    # Make sure to only send integers to the devpip install PyCRCice. Otherwise it won't work.
    def create_a_waveform_file(self, voltages, fname="waveform.txt"):
        fname = os.path.join(self.path_to_folder, fname)
        line = ""
        for v in voltages:
            line += str(format(int(v), "#04x"))
            line += ";"
        with open(fname, "w") as fp:
            fp.write(line[:-1])
        print(f"Stored waveform in {fname}")

    def get_waveform_from_file(self, fname="waveform.txt"):
        fname = os.path.join(self.path_to_folder, fname)
        with open(fname, "r") as fp:
            inpt = fp.read()
        waveform_hex = inpt.split(";")
        waveform_int = np.zeros(len(waveform_hex))
        for i in range(len(waveform_hex)):
            waveform_int[i] = int(waveform_hex[i], 16)
        return waveform_int

    def plot_waveform_from_file(self, fname="waveform.txt"):
        fname = os.path.join(self.path_to_folder, fname)
        waveform = self.get_waveform_from_file(fname)
        plt.plot(waveform)
        plt.xlabel("bit")
        plt.ylabel("amp")
        plt.ylim([0, 255])
        plt.show()

    def create_gauss(self, width, amp=255):
        if amp > 255:
            raise Exception("amp needs to be 255 or less.")
        voltages = np.zeros((512,))

        offset_index = 256
        gauss = lambda i,: amp * np.exp(-((i - offset_index) ** 2.0) / width**2.0)

        for index in range(512):
            voltages[index] = gauss(index)
        voltages = np.around(voltages)
        return voltages

    def create_pulse(self, pulse_width: float, pulse_delay: float, pulse_shape: str = "square", pulse_amplitude: int = 255):
        """Creates a pulse with the given parameters and returns the corresponding waveform as an array of integers.
        pulse_width: width of the pulse in ns
        pulse_delay: delay of the pulse in ns
        pulse_shape: shape of the pulse, either 'square' or 'gaussian'
        pulse_amplitude: amplitude of the pulse, between 0 and 255
        """

        pulse_width_bins = int(pulse_width / 0.2)
        pulse_delay_bins = int(pulse_delay / 0.2)

        waveform = np.zeros((512,))

        if pulse_amplitude > 255:
            raise ValueError("amp needs to be 255 or less.")
        if pulse_width_bins + pulse_delay_bins > 512:
            raise ValueError("pulse width + pulse delay needs to be shorter then 104 ns.")

        match pulse_shape:
            case "square":
                waveform = np.zeros((512,))
                waveform[pulse_delay_bins : pulse_width_bins + pulse_delay_bins] = np.ones(pulse_width_bins) * pulse_amplitude
            case "gaussian":
                sigma = pulse_width_bins / (2 * np.sqrt(2 * np.log(2)))  # pulse_width_bins is FWHM
                center = pulse_delay_bins + 3 * sigma

                bins = np.arange(512)
                waveform = np.around(pulse_amplitude * np.exp(-((bins - center) ** 2) / (2 * sigma**2)))

        return waveform

    def create_pulses(self, num_pulses, width, spacing, amp=255, pulse_shape="square", initial_delay=0):

        voltages = np.zeros((512,))
        if amp > 255:
            raise Exception("amp needs to be 255 or less.")

        if num_pulses * (width + spacing) - spacing > 512:
            raise Exception("length of pulsetrain needs to be 512 bits or less.")

        # start point of puls is here the rising flank of the square pulse (not the middle)
        if pulse_shape == "square":
            pos = initial_delay
            for i in range(num_pulses):
                voltages[pos : pos + width] = np.ones(width) * amp
                pos += width + spacing
        # start point of the pulse is here the maximum (middle) of the gaussian peak
        elif pulse_shape == "gauss":
            sigma = width / (2 * np.sqrt(2 * np.log(2)))
            if initial_delay == 0:
                initial_delay = width

            # Generate pulses
            for i in range(num_pulses):
                # Calculate the center of each pulse
                center = i * spacing + initial_delay

                # Generate the Gaussian pulse
                x = np.arange(512)

                pulse = amp * np.exp(-((x - center) ** 2) / (2 * sigma**2))

                # Add the pulse to the output array
                voltages += pulse

        else:
            raise Exception("Typo or pulse shape not (yet) availible.")

        return np.around(voltages)

    def create_ramp(self, len, amp=255):
        if len > 512:
            raise Exception("len needs to be 512 or less.")
        if amp > 255:
            raise Exception("amp needs to be 255 or less.")
        voltages = np.zeros((512,))
        ramp = np.linspace(0, amp, len)
        for index in range(len):
            voltages[index] = ramp[index]
        voltages = np.around(voltages)
        return voltages

    def create_triangle(self, amp=255):
        if amp > 255:
            raise Exception("amp needs to be 255 or less.")
        voltages = np.zeros((512,))
        len = 256
        ramp = np.linspace(0, amp, len)
        for index in range(len):
            voltages[index] = ramp[index]
        for index in range(len):
            voltages[index + len] = np.flip(ramp)[index]
        voltages = np.around(voltages)
        return voltages

    def create_square(self, len, amp=255):
        if len > 512:
            raise Exception("len needs to be 512 or less.")
        if amp > 255:
            raise Exception("amp needs to be 255 or less.")
        voltages = np.zeros((512,))
        voltages[:len] = np.ones(len) * amp
        return voltages

    def create_zero(self):
        voltages = np.zeros((512,))
        return voltages

    def create_sine(self, amp):
        if amp > 255:
            raise Exception("amp needs to be 255 or less.")
        voltages = np.zeros((512,))
        for i in range(512):
            voltages[i] = round(amp * (1 + np.sin(2 * np.pi * i / 512)) / 2)
        return voltages


class PPG512(Base):
    # How to write a waveform:
    # # instances so you know what they refer to
    # wg = waveform_generation()
    # ppg = ppg512()
    # # create the waveform and save them in a file, can be omitted it waveform is already in file
    # wg.create_a_waveform_file(wg.create_square(50,amp=255), 'waveform.txt')
    # # plot the waveform (not necessary but nice to see what is going on)
    # wg.plot_waveform_from_file('waveform.txt')
    # # take the wavform from the file and send it to the device
    # ans = ppg.write_waveform(fname='waveform.txt')
    """
    picoquant_ppg512:
    module.Class: 'picoquant.ppg512.PPG512'
    options:
        port: 'COM10'
        vccrf : 15000
        vref : 400

    """
    _port = ConfigOption(name="port", missing="warn")
    _vccrf = ConfigOption(name="vccrf", missing="warn")
    _vref = ConfigOption(name="vref", missing="warn")

    def __init__(self, port=None, **kwargs):
        if port:
            self._port = port
        self.wg = waveform_generation()
        self.path_to_folder = os.path.dirname(os.path.abspath(__file__))
        super().__init__(**kwargs)

    def on_activate(self):
        self.connect()
        self.log.info(f"PPG512 IDN: {self._query('*IDN?')}")
        time.sleep(1)
        # set voltages to values specified in config
        self.set_vccrf(self._vccrf)
        time.sleep(1)
        self.set_vref(self._vref)
        time.sleep(1)
        print(self.get_vccrf())
        time.sleep(1)
        print(self.get_vref())
        return

    def on_deactivate(self):
        # set amplifier voltage to min to reduce heating
        self.set_vccrf(12000)
        # also minimise reference voltage to acieve minimal output voltage
        self.set_vref(0)
        # set output to zero (aka. minimal possible voltage)
        self.constant_output()
        self.ser.close()

    def connect(self):
        self.ser = serial.Serial(port=self._port, baudrate=115200, bytesize=8, parity=serial.PARITY_NONE, stopbits=1, timeout=2)
        return

    def _write(self, cmd, eol="\r"):
        cmd += eol  # end of line marker
        cmd = bytes(cmd, "UTF-8")  # turn into bytes
        a = self.ser.write(cmd)
        return

    def _query(self, cmd, eol="\r", delay=0.1):
        """Sends a command to the decive and returns the response.

        System responses are:
            BUSY system is busy and can therefore not handle command
            ACK response for every correct set command (ends with '!')
            NACK response for commands with wrong parameter
            COMMAND UNKNOWN wrong or misspelled command
        """
        time.sleep(delay)
        self._write(cmd, eol)
        time.sleep(delay)  # if you read right after sending a command, you get an empty string
        ans = self.ser.read_all()
        return ans

    def get_state(self):
        ans = self._query("SYS:STAT?")
        return ans

    def get_report(self):
        ans = self._query("SYS:REP?")
        return ans

    def reset(self):
        """Reset System

        System restarts with stored values.
        """
        ans = self._query("SYS:RES!", delay=3)
        return ans

    def set_vref(self, vref):
        """Sets VREF to vref in mV. Max 2V.

        VREF is stored DAC reference voltage.
        This is the max voltage that device will give out (when 256 is given as value in waveform).
        """
        ans = self._query(f"SOUR:VOLT:VREF {vref}!")
        return ans

    def get_vref(self):
        """Returns VREF in mV."""
        ans = self._query("SOUR:VOLT:VREF?")
        return ans

    def set_vccrf(self, vccrf):
        """Sets VCCRF to vccrf in mV. Possible values are 12V to 24V

        VCCRF is supply voltage for RF amplifier.
        Set it as low as possible to minimize heating.
        """
        ans = self._query(f"SOUR:VOLT:VCCRF {vccrf}!")
        return ans

    def get_vccrf(self):
        """Returns VCCRF in mV."""
        ans = self._query("SOUR:VOLT:VCCRF?")
        return ans

    def write_waveform(self, file_name="waveform.txt", nr_attempts=1):
        waveform_points = []
        file_path = os.path.join(self.path_to_folder, file_name)
        with open(file_path) as fp:
            data = csv.reader(fp, delimiter=";")
            for row in data:
                for column in row:
                    waveform_points.append(column)

        # Add checksum at end of waveform data, needs to be calculated from the hex values of the waveform data
        check_sum = get_chck_summ(file_path)
        waveform_points.append("0x" + str(check_sum)[2:4])
        waveform_points.append("0x" + str(check_sum)[4:6])
        query = ""
        for point in waveform_points:
            query += point
            query += ";"

        query = query[:-1]

        # It is important to read out the memory after sending 'SYS:DATA!' --> use _query
        # If you don't do this, the device will not change the waveform.

        for _ in range(nr_attempts):
            # Check if the PPG acknowledged the data transfer command (twice))
            if self._query("SYS:DATA!").decode("ascii") != "SYS:DATA!\r\r\nACK\r\n":
                if self._query("SYS:DATA!").decode("ascii") != "SYS:DATA!\r\r\nACK\r\n":
                    raise ConnectionError("PPG did not acknowledge the data transfer command.")

            ans = self._query(query, eol="")

            if "nack" in ans.decode("ascii").lower():
                self.log.warning(f"Reseting PPG - Could not write waveform!: {ans}")
                self.reset()
                self.reset()
                time.sleep(5)
            elif "ack" in ans.decode("ascii").lower():
                self.log.info(f"Successfully wrote waveform: {ans}")
                return ans
            else:
                self.log.warning(f"Reseting PPG - Could not write waveform!: {ans}")
                self.reset()
                time.sleep(1)
                self.reset()
                time.sleep(5)

        raise TimeoutError("Timeout - Could not write waveform!")

    def constant_output(self):
        self.wg.create_a_waveform_file(self.wg.create_zero(), fname="temp.txt")
        ans = self.write_waveform(fname="temp.txt")

    def write_pulse(self, pulse_width: float, pulse_shape: str, pulse_delay: float = 0, pulse_amplitude: int = 255):
        waveform = self.wg.create_pulse(pulse_width, pulse_delay, pulse_shape, pulse_amplitude)
        self.wg.create_a_waveform_file(waveform, fname=pulse_shape + ".txt")
        ans = self.write_waveform(file_name=pulse_shape + ".txt")
        print(ans)
        return True
