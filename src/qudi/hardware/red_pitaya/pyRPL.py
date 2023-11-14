import time
import serial

from qudi.core.module import Base
from qudi.core.configoption import ConfigOption
from qudi.interface.motor_interface import MotorInterface

from pyrpl import Pyrpl


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
    