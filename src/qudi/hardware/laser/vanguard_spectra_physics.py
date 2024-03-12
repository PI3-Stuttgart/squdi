try:
    import pyvisa as visa

except ImportError:
    import visa
from qudi.core.configoption import ConfigOption
from qudi.interface.simple_laser_interface import SimpleLaserInterface
from qudi.interface.simple_laser_interface import ControlMode, ShutterState, LaserState
from qudi.core.module import Base

def query(instr, msg):
    instr.write(('%s\n'% msg).encode('ascii'))
    return instr.readline().decode() # unicode
def writefunc(instr, msg):
    instr.write(('%s\n'% msg).encode('ascii'))

    
class VanguardPulsedLaser(Base):
    """ Spectra Physics Millennia diode pumped solid state laser.

    Example config for copy-paste:

    millennia_laser:
        module.Class: 'laser.millennia_ev_laser.MillenniaeVLaser'
        options:
            interface: 'ASRL1::INSTR'
            maxpower: 25 # in Watt
    """
    serial_interface = ConfigOption(name='interface', default='COM7', missing='warn')


    def on_activate(self):
        """ Activate Module.
        """
        self.connect_laser()

    def on_deactivate(self):
        """ Deactivate module
        """
        self.disconnect_laser()

    def connect_laser(self):
        """ Connect to Instrument.

            @param str interface: visa interface identifier

            @return bool: connection success
        """
        try:
            self.rm = visa.ResourceManager()
            rate = 115200
            self.inst = self.rm.open_resource(self.serial_interface,
                write_termination='\n',
                read_termination='\n')

            self.inst.timeout = 1000
            idn = self.inst.query('*IDN?')
            (self.mfg, self.model, self.serial, self.version) = idn.split(',')
        except visa.VisaIOError as e:
            self.log.exception('Communication Failure:')
            return False
        else:
            return True

    def disconnect_laser(self):
        """ Close the connection to the instrument.
        """
        self.inst.close()
        self.rm.close()

    def get_power(self):
        """ Current laser power

        @return float: laser power in watts
        """
        return float(self.inst.query('?PSET').replace("W", ""))

    
    def get_shutter_state(self):
        """ Get laser shutter state

        @return ShutterState: current laser shutter state
        """
        state = int(self.inst.query('?SHUTTER'))
        if state == 1:
            return ShutterState.OPEN
        elif state == 0:
            return ShutterState.CLOSED
        else:
            return ShutterState.UNKNOWN
        
    def set_shutter_state(self, state):
        """ Set laser shutter state.

        @param ShuterState state: desired laser shutter state
        @return ShutterState: actual laser shutter state
        """
        if state != self.get_shutter_state():
            if state == ShutterState.OPEN:
                self.inst.query('SHUTTER:1')
            elif state == ShutterState.CLOSED:
                self.inst.query('SHUTTER:0')

    def get_crystal_temperature(self):
        """ Get SHG crystal temerpature.

        @return float: SHG crystal temperature in degrees Celsius
        """
        return float(self.inst.query('?SHG'))

    def get_diode_temperature(self):
        """ Get laser diode temperature.

        @return float: laser diode temperature in degrees Celsius
        """
        return float(self.inst.query('?T'))
    
    def get_temperatures(self):
        """ Get all available temperatures

        @return dict: dict of temperature names and values
        """
        return {
            'crystal': self.get_crystal_temperature(),
            'diode': self.get_diode_temperature(),
            'tower': self.get_tower_temperature(),
            'cab': self.get_cab_temperature()
        }
    
    def on(self):
        return float(self.inst.query('ON'))

    def off(self):
        return float(self.inst.query('OFF'))
