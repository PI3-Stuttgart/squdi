from qtpy import QtCore

from qudi.interface.wavemeter_interface import WavemeterInterface
from PySide2 import QtCore
from qudi.core.configoption import ConfigOption
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
        except:
            return 
        finally:
            self.tcp_client.close()
        return res
    return wrapper

    
class HighFinesseWavemeterClient(WavemeterInterface):
    wavelengths = np.array([])
    queryInterval = 20
    buffer_length = 10000
    sig_send_request = QtCore.Signal(str, str)

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        #locking for thread safety
        self._current_wavelength = 0.0
        self.wlm_time = np.zeros((1, 2)) 

    def on_activate(self):
        self.host_ip, self.server_port = '129.69.46.209', 1243
        # self.tcp_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #self.sig_send_request.connect(self.send_request, QtCore.Qt.QueuedConnection)
        # self.queryTimer = QtCore.QTimer()
        # self.queryTimer.setInterval(self.queryInterval)
        # self.queryTimer.setSingleShot(True)
        # self.queryTimer.timeout.connect(self.loop_body)#, QtCore.Qt.QueuedConnection)     
        # self.queryTimer.start(self.queryInterval)

    @QtCore.Slot()
    def loop_body(self):
        self.queryTimer.start(self.queryInterval)
        self.wavelengths = np.append(self.wavelengths, self.__get_wavelength())[-self.buffer_length:]

    @connect
    @QtCore.Slot(str, str)
    def send_request(self, request, action=None):
        action = None if action == '' else action
        self.tcp_client.sendall(request.encode())
        received = self.tcp_client.recv(10024)
        response = pickle.loads(received[1:])
        flag = received[:1].decode()
        if flag == 'c':
            #get wavelength
            self.wlm_time = np.vstack((self.wlm_time, response))
            return response[0]
        elif flag == 'k':
            if action != None:
                self.tcp_client.sendall(action.encode())
            else:
                print("Set action! ")
        elif flag == 'u':
            return response
    
    def on_deactivate(self):
        self.tcp_client.close()

    def start_acquisition(self):
        return self.send_request("start_measurements")

    def stop_acquisition(self):
        return self.send_request("stop_measurements")

    def start_trigger(self):
        return self.send_request("start_trigger")

    def stop_trigger(self):
        return self.send_request("stop_trigger")

    def get_wavelengths(self):
        """ This method returns the current wavelength in air.
        """
        return self.send_request("get_wavelengths") # gets 1000 entries recorded ~ approx whithin 1 s or return [] if the buffer is not filled

    def get_regulation_mode(self):
        return self.send_request("get_regulation_mode")

    def set_regulation_mode(self, mode):
        return self.send_request("set_regulation_mode", action=mode)

    def get_reference_course(self):
        return self.send_request("get_reference_course")

    def set_reference_course(self, course):
        return self.send_request("set_reference_course", action=course)
        
    def get_server_time(self):
        return self.send_request("get_server_time")
    
    def sync_clocks(self):
        # to sync time stamps and wavelengths add delta t to the current time of the client
        times = np.array([])
        for t in range(1000):
            times = np.append(times, time.time() - self.get_server_time())
            #delay(0.25)
        return times.mean()

    def get_current_wavelength(self, kind="freq"):
        """ This method returns the current wavelength.

        @param (str) kind: can either be "air" or "vac" for the wavelength in air or vacuum, respectively.

        @return (float): wavelength (or negative value for errors)
        """
        #   if kind == "freq":
        #        return self.wavelength_to_freq(self.wavelengths[-1]) if len(self.wavelengths) > 0 else -1
        #    else:
        return self.send_request("get_wavelength") #1e12 * self.wavelengths[-1] if len(self.wavelengths) > 0 else -1

    def get_current_wavelength2(self, kind="air"):
        """ This method returns the current wavelength of the second input channel.

        @param (str) kind: can either be "air" or "vac" for the wavelength in air or vacuum, respectively.

        @return float: wavelength (or negative value for errors)
        """
        pass

    def get_timing(self):
        """ Get the timing of the internal measurement thread.

        @return (float): clock length in second
        """
        pass

    def set_timing(self, timing):
        """ Set the timing of the internal measurement thread.

        @param (float) timing: clock length in second

        @return (int): error code (0:OK, -1:error)
        """
        pass

    def wavelength_to_freq(self, wavelength):
        if isinstance(wavelength, float):
            return 299792458.0 * 1e9 / wavelength
        wavelength = np.array(wavelength)
        aa = 299792458.0 * 1e9 * np.ones(wavelength.shape[0])
        freqs = np.divide(aa, wavelength, out=np.zeros_like(aa), where=wavelength!=0)
        return freqs

    def empty_buffer(self):
        return self.send_request("empty_buffer")