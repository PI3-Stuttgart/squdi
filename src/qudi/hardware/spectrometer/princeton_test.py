from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.interface.spectrometer_interface import SpectrometerInterface

import numpy as np
import seabreeze.spectrometers as sb


class Princeton(SpectrometerInterface):
    """ Hardware module for reading spectra from the Princeton Optics spectrometer software.

    Example config for copy-paste:

    myspectrometer:
        module.Class: 'spectrometer.oceanoptics_spectrometer.OceanOptics'
        options:
            spectrometer_serial: 'QEP01583' #insert here the right serial number.

    """
    #_serial = ConfigOption(name='spectrometer_serial', default=None, missing='warn')
    _integration_time = StatusVar(name='integration_time', default=0.1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spectrometer = None

    def on_activate(self):
        """ Activate module.
        """
        self.log.info(f'available spectrometers: {sb.list_devices()}')
        #self._spectrometer = sb.Spectrometer.from_serial_number(self._serial)
        self._spectrometer.features['thermo_electric'][0].set_temperature_setpoint_degrees_celsius(-22)
        #self.log.info(''.format(self._spectrometer.model, self._spectrometer.serial_number))
        self.exposure_time = self._integration_time
        self.log.info(f'Exposure set to {self._integration_time} seconds')

    def on_deactivate(self):
        """ Deactivate module.
        """
        self._spectrometer.close()

    def record_spectrum(self):
        """ Record spectrum from Ocean Optics spectrometer.

            @return []: spectrum data
        """
        wavelengths = self._spectrometer.wavelengths()
        specdata = np.empty((2, len(wavelengths)), dtype=np.double)
        specdata[0] = wavelengths / 1e9
        specdata[1] = self._spectrometer.intensities()
        return specdata

    @property
    def exposure_time(self):
        """ Get exposure.
            @return float: exposure time
            Not implemented.
        """
        return self._integration_time

    @exposure_time.setter
    def exposure_time(self, value):
        """ Set exposure.
            @param float value: exposure time in seconds
        """
        assert isinstance(value, (float, int)), f'exposure_time needs to be a float in seconds, but was {value}'
        self._integration_time = float(value)
        self._spectrometer.integration_time_micros(int(self._integration_time * 1e6))

    def clearBuffer(self):
        self._spectrometer.features['data_buffer'][0].clear()

    @property
    def grating(self):
        """ Get current grating.
            @return int: current grating number
        """
        return self._spectrometer.grating

    @grating.setter
    def grating(self, value):
        """ Set grating.
            @param int value: grating number to set (typically 1 or 2)
        """
        assert isinstance(value, (float, int)), f'grating needs to be a number, but was {value}'
        self._spectrometer.grating = int(value)

    @property
    def cwavelength(self):
        """ Get center wavelength.
            @return float: current center wavelength in meters
        """
        return self._spectrometer.cwavelength

    @cwavelength.setter
    def cwavelength(self, value):
        """ Set center wavelength.
            @param float value: center wavelength in meters
        """
        assert isinstance(value, (float, int)), f'center wavelength needs to be a number in meters, but was {value}'
        self._spectrometer.cwavelength = float(value)