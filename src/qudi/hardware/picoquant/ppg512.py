# pip install pyserial
import serial
import csv
import numpy as np
from qudi.hardware.picoquant.crc import get_chck_summ, get_chck_summ_from_array
import time
import os

from qudi.core.module import Base
from qudi.core.configoption import ConfigOption


class WaveformGeneration:
    def __init__(self):
        self.path_to_folder = os.path.dirname(os.path.abspath(__file__))

    # Make sure to only send integers to the device. Otherwise it won't work.
    def create_a_waveform_file(self, voltages, fname='waveform.txt'):
        fname = os.path.join(self.path_to_folder, fname)
        line = ''
        for v in voltages:
            line += str(format(int(v), '#04x'))
            line += ';'
        with open(fname, 'w') as fp:
            fp.write(line[:-1])
        print(f'Stored waveform in {fname}')

    def get_waveform_from_file(self, fname='waveform.txt'):
        if not os.path.isabs(fname):
            fname = os.path.join(self.path_to_folder, fname)
        with open(fname, 'r') as fp:
            inpt = fp.read()
        waveform_hex = inpt.split(';')
        waveform_int = np.zeros(len(waveform_hex))
        for i in range(len(waveform_hex)):
            waveform_int[i] = int(waveform_hex[i], 16)
        return waveform_int

    def plot_waveform_from_file(self, fname='waveform.txt'):
        import matplotlib.pyplot as plt
        if not os.path.isabs(fname):
            fname = os.path.join(self.path_to_folder, fname)
        waveform = self.get_waveform_from_file(fname)
        plt.plot(waveform)
        plt.xlabel('bit')
        plt.ylabel('amp')
        plt.ylim([0, 255])
        plt.show()

    def create_gauss(self, width, amp=255, offset_index=256):
        if amp > 255:
            raise ValueError('amp needs to be 255 or less.')
        voltages = np.zeros((512,))

        gauss = lambda i: amp * np.exp(-(i - offset_index)**2.0 / width**2.0)

        for index in range(512):
            voltages[index] = gauss(index)
        voltages = np.around(voltages)
        return voltages
    
    def create_gaussian_train(self, width, amp=255, posi0=0, spacing=10, n=1):
        if amp > 255:
            raise ValueError('amp needs to be 255 or less.')
        voltages = np.zeros((512,))
        sigma = width / (2 * np.sqrt(2 * np.log(2)))
        
        for i in range(n):
            center = posi0 + i * spacing
            x = np.arange(512)
            pulse = amp * np.exp(-(x - center)**2 / (2 * sigma**2))
            voltages += pulse
        
        return np.around(voltages)

    def create_pulses(self, num_pulses, width, spacing, amp=255, pulse_shape='square', initial_delay=0):
        voltages = np.zeros((512,))
        if amp > 255: raise ValueError('amp needs to be 255 or less.')
        if num_pulses * (width + spacing) - spacing > 512: 
            raise ValueError('length of pulsetrain needs to be 512 bits or less.')

        if pulse_shape == 'square':    
            pos = initial_delay 
            for i in range(num_pulses):
                voltages[pos:pos+width] = np.ones(width) * amp
                pos += width + spacing
        elif pulse_shape == 'gauss': 
            sigma = width / (2 * np.sqrt(2 * np.log(2)))
            if initial_delay == 0:
                initial_delay = width
                
            for i in range(num_pulses):
                center = i * spacing + initial_delay
                x = np.arange(512)
                pulse = amp * np.exp(-(x - center)**2 / (2 * sigma**2))
                voltages += pulse
        else:
            raise ValueError('Typo or pulse shape not (yet) available.')

        return np.around(voltages)

    def create_ramp(self, length, amp=255):
        if length > 512:
            raise ValueError('length needs to be 512 or less.')
        if amp > 255:
            raise ValueError('amp needs to be 255 or less.')
        voltages = np.zeros((512,))
        ramp = np.linspace(0, amp, length) 
        for index in range(length):
            voltages[index] = ramp[index]
        voltages = np.around(voltages)
        return voltages

    def create_triangle(self, amp=255):
        if amp > 255:
            raise ValueError('amp needs to be 255 or less.')
        voltages = np.zeros((512,))
        length = 256
        ramp = np.linspace(0, amp, length) 
        for index in range(length):
            voltages[index] = ramp[index]
        for index in range(length):
            voltages[index+length] = np.flip(ramp)[index]
        voltages = np.around(voltages)
        return voltages
    
    def create_square(self, length, amp=255):
        if length > 512:
            raise ValueError('length needs to be 512 or less.')
        if amp > 255:
            raise ValueError('amp needs to be 255 or less.')
        voltages = np.zeros((512,))
        voltages[:length] = np.ones(length) * amp
        return voltages
            
    def create_zero(self):
        voltages = np.zeros((512,))
        return voltages

    def create_sine(self, amp):
        if amp > 255:
            raise ValueError('amp needs to be 255 or less.')
        voltages = np.zeros((512,))
        for i in range(512):
            voltages[i] = round(amp * (1 + np.sin(2 * np.pi * i / 512)) / 2)
        return voltages


class PPG512(Base):
    """
    picoquant_ppg512:
    module.Class: 'picoquant.ppg512.PPG512'
    options:
        port: 'COM10'
        vccrf : 15000
        vref : 400
    """
    _port = ConfigOption(name='port', missing='warn')
    _vccrf = ConfigOption(name='vccrf', missing='warn')
    _vref = ConfigOption(name='vref', missing='warn')

    def __init__(self, port=None, **kwargs):
        if port:
            self._port = port
        self.wg = WaveformGeneration()
        self.path_to_folder = os.path.dirname(os.path.abspath(__file__))
        self.ser = None
        super().__init__(**kwargs)

    def on_activate(self):
        self.connect()
        print(self._query('*IDN?'))
        time.sleep(1)
        # set voltages to values specified in config
        if self._vccrf is not None:
            self.set_vccrf(self._vccrf)
            time.sleep(1)
        if self._vref is not None:
            self.set_vref(self._vref)
            time.sleep(1)
        print("VCCRF:", self.get_vccrf())
        time.sleep(1)
        print("VREF:", self.get_vref())

    def on_deactivate(self):
        try:
            # set amplifier voltage to min to reduce heating
            self.set_vccrf(12000)
            # also minimise reference voltage to achieve minimal output voltage
            self.set_vref(0)
            # set output to zero (aka. minimal possible voltage)
            self.constant_output()
        except Exception as e:
            if hasattr(self, 'log'):
                self.log.error(f"Error during deactivation: {e}")
            else:
                print(f"Error during deactivation: {e}")
        finally:
            if self.ser and self.ser.is_open:
                self.ser.close()

    def connect(self):
        _port = self._port #'COM10'
        self.ser = serial.Serial(port=_port, baudrate=115200, bytesize=8, parity=serial.PARITY_NONE, stopbits=1, timeout=2)

    def _write(self, cmd, eol='\r'):
        cmd += eol # end of line marker
        cmd = bytes(cmd, 'UTF-8') # turn into bytes
        self.ser.write(cmd)

    def _query(self, cmd, eol='\r', delay=0.75):
        time.sleep(delay)
        self._write(cmd, eol)
        time.sleep(delay) 
        ans = self.ser.read_all()
        return ans

    def get_state(self):
        ans = self._query('SYS:STAT?')
        return ans

    def get_report(self):
        ans = self._query('SYS:REP?')
        return ans

    def reset(self):
        ans = self._query('SYS:RES!', delay=3)
        return ans

    def set_vref(self, vref):
        ans = self._query(f'SOUR:VOLT:VREF {vref}!')
        return ans

    def get_vref(self):
        ans = self._query('SOUR:VOLT:VREF?')
        return ans

    def set_vccrf(self, vccrf):
        ans = self._query(f'SOUR:VOLT:VCCRF {vccrf}!')
        return ans

    def get_vccrf(self):
        ans = self._query('SOUR:VOLT:VCCRF?')
        return ans

    def write_waveform(self, voltages=None, fname=None):
        if voltages is not None:
            ans = self.write_waveform_from_array(voltages)
        elif fname:
            ans = self.write_waveform_from_file(fname=fname)
        return ans

    def write_waveform_from_array(self, voltages):
        check_sum = get_chck_summ_from_array(voltages)
        check_sum_str = str(check_sum)[2:].zfill(4)
        
        value = [str(format(int(v), '#04x')) for v in voltages]
        value.append('0x' + check_sum_str[0:2])
        value.append('0x' + check_sum_str[2:4])
        
        to_write = ';'.join(value)

        self._query('SYS:DATA!')
        ans = self._query(to_write, eol='')
        if hasattr(self, 'log'):
            self.log.info('Wrote waveform from array to device.')
        else:
            print('Wrote waveform from array to device.')
        return ans

    def write_waveform_from_file(self, fname='waveform.txt'):
        value = []
        if not os.path.isabs(fname):
            fname = os.path.join(self.path_to_folder, fname)
        with open(fname) as fp:
            data = csv.reader(fp, delimiter=';')
            for row in data:
                for column in row:
                    value.append(column)

        check_sum = get_chck_summ(fname)
        check_sum_str = str(check_sum)[2:].zfill(4)
        value.append('0x' + check_sum_str[0:2])
        value.append('0x' + check_sum_str[2:4])
        
        to_write = ';'.join(value)

        self._query('SYS:DATA!')
        ans = self._query(to_write, eol='')
        if hasattr(self, 'log'):
            self.log.info(f'Wrote waveform from {fname} to device.')
        else:
            print(f'Wrote waveform from {fname} to device.')
        return ans

    def constant_output(self):
        voltages = self.wg.create_zero()
        ans = self.write_waveform_from_array(voltages)
        return ans