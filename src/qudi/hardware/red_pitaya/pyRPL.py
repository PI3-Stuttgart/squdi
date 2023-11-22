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
            self.rpl = Pyrpl(self._config, gui=None)
        else:
            self.rpl = Pyrpl(self._hostname, gui=None)
        self.rp = self.rpl.rp

    def on_deactivate(self):
        self.rpl.close()

