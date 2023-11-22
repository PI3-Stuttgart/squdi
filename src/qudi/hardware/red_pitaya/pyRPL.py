import time
import serial

from qudi.core.module import Base
from qudi.core.configoption import ConfigOption
from qudi.interface.motor_interface import MotorInterface

from pyrpl import Pyrpl, RedPitaya
"""
# default parameters for redpitaya object creation
defaultparameters = dict(
    hostname='', #'192.168.1.100', # the ip or hostname of the board, '' triggers gui
    port=2222,  # port for PyRPL datacommunication
    sshport=22,  # port of ssh server - default 22
    user='root',
    password='root',
    delay=0.05,  # delay between ssh commands - console is too slow otherwise
    autostart=True,  # autostart the client?
    reloadserver=False,  # reinstall the server at startup if not necessary?
    reloadfpga=True,  # reload the fpga bitfile at startup?
    serverbinfilename='fpga.bin',  # name of the binfile on the server
    serverdirname = "//opt//pyrpl//",  # server directory for server app and bitfile
    leds_off=True,  # turn off all GPIO lets at startup (improves analog performance)
    frequency_correction=1.0,  # actual FPGA frequency is 125 MHz * frequency_correction
    timeout=1,  # timeout in seconds for ssh communication
    monitor_server_name='monitor_server',  # name of the server program on redpitaya
    silence_env=False,   # suppress all environment variables that may override the configuration?
    gui=True  # show graphical user interface or work on command-line only?
    )

    """

class PyRPL(Base):
    """ Gives an interface to the red pitaya. """
    _hostname = ConfigOption('hostname', '192.168.202.72', missing='nothing')
    _config = ConfigOption('config', missing='warn')
    
    def on_activate(self):
        if self._config:
            self.rpl = Pyrpl(self._config).redpitaya
        else:
            self.rpl = Pyrpl(self._hostname).redpitaya

    def on_deactivate(self):
        self.rpl.close()


    def generate_signal(self, source = 0, waveform='dc', amplitude=1, frequency=0, output_direct='out2'):
        if source == 0:
            return self.rpl.asg0.setup(
                waveform=waveform, amplitude=amplitude, frequency=frequency, output_direct=output_direct
            )
        elif source == 1:
            return self.rpl.asg1.setup(
                waveform=waveform, amplitude=amplitude, frequency=frequency, output_direct=output_direct
            )
        else:
            return -1
    
    def iq_demodulation(self,source = 0, input='iq0',
            frequency=10e6,  # demodulaltion at 10 MHz
            bandwidth=1e5):  # demodulation bandwidth of 100 kHz
        if source == 0:
            return self.rpl.iq0.setup(
                input=input,
                frequency=frequency,
            bandwidth=bandwidth
            )
        elif source == 1:
            return self.rpl.iq0.setup(
                input=input,
                frequency=frequency,
            bandwidth=bandwidth
            )
        else:
            return -1
    
    def pid(self,source = 0,
            input='iq0',
             output_direct='out2',  # add pid signal to output 2
             setpoint=0.05, # pid setpoint of 50 mV
             p=0.1,  # proportional gain factor of 0.1
             i=100,  # integrator unity-gain-frequency of 100 Hz
             input_filter = [3e3, 10e3]):  # add 2 low-passes (3 and 10 kHz)
        if source == 0:
            return self.rpl.pid0.setup(
                input=input,
             output_direct=output_direct,  # add pid signal to output 2
             setpoint=setpoint, # pid setpoint of 50 mV
             p=p,  # proportional gain factor of 0.1
             i=i,  # integrator unity-gain-frequency of 100 Hz
             input_filter = input_filter
            )
        elif source == 1:
            return self.rpl.pid1.setup(
                input=input,
             output_direct=output_direct,  # add pid signal to output 2
             setpoint=setpoint, # pid setpoint of 50 mV
             p=p,  # proportional gain factor of 0.1
             i=i,  # integrator unity-gain-frequency of 100 Hz
             input_filter = input_filter
            )
        else:
            return -1
    