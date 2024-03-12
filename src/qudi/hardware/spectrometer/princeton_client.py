from qudi.interface.spectrometer_interface import SpectrometerInterface
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar

import socket
import numpy as np
import pickle
import time

def connect(func):
    def wrapper(self, *arg, **kw):
        try:
            # Establish connection to TCP server and exchange data
            self.tcp_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_client.connect((self.host_ip, self.server_port))
            res = func(self, *arg, **kw)
        finally:
            self.tcp_client.close()
        return res
    return wrapper

    
class PrincetonSpectrometerClient(SpectrometerInterface):
    _integration_time = StatusVar(name='integration_time', default=10)
    _ip = ConfigOption('ip', missing='error')
    _port = ConfigOption('port', 3336, missing='warn')
    _shift_wavelength = 0.57274
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        #locking for thread safety
        self.wavelength = np.linspace(0, 1339, 1340)
        

    def on_activate(self):
        self.host_ip, self.server_port = self._ip, self._port
        try:
            self.exposure_time = self._integration_time
        except:
            print("Prolly the scpectrometer is not attached")
        # self.tcp_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
    @connect
    def send_request(self, request, action=None, recv_bytes = 1024):
        self.tcp_client.sendall(request.encode())
        received = self.tcp_client.recv(recv_bytes)
        response = pickle.loads(received[1:], encoding="latin1")
        flag = received[:1].decode()
        
        if flag == 'k':
            if action != None:
                self.tcp_client.sendall(action.encode())
            else:
                print("Set action! ")
        elif flag == 'u':
            return response
    
    def on_deactivate(self):
        self.tcp_client.close()

    def record_spectrum(self):
       
        wavelengths = self.send_request("get_wavelength", recv_bytes = 32768)
        specdata = np.empty((2, len(wavelengths)), dtype=np.double)
        specdata[0] = wavelengths + self._shift_wavelength
        specdata[1] = self.send_request("get_spectrum", recv_bytes = 32768)
        return specdata
    

    def clearBuffer(self):
        pass
    
    @property
    def exposure_time(self):
        """ Get exposure.
            @return float: exposure time
            Not implemented.
        """
        return self.send_request("get_exposure_time") / 1000
    
    @exposure_time.setter
    def exposure_time(self, value):
        """ Set exposure.
            @param float value: exposure time in seconds
        """
        assert isinstance(value, (float, int)), f'exposure_time needs to be a float in seconds, but was {value}'
        self._integration_time = float(value)
        self.send_request("set_exposure_time", action=str(self._integration_time* 1000))
