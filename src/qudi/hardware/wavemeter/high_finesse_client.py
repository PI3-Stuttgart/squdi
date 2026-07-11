from qtpy import QtCore

from qudi.interface.wavemeter_interface import WavemeterInterface
from PySide2 import QtCore
from qudi.core.configoption import ConfigOption
import socket
import numpy as np
import pickle
import time

import struct

def recv_exact(sock, n):
    """ Helper function to recv exactly n bytes or return None if EOF is hit """
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return bytes(data)

def recv_framed_msg(sock):
    """ Receives a framed message: returns (flag, payload_bytes) """
    raw_msglen = recv_exact(sock, 4)
    if not raw_msglen:
        return None, None
    msglen = struct.unpack("!I", raw_msglen)[0]
    data = recv_exact(sock, msglen)
    if not data:
        return None, None
    return data[:1].decode('utf-8'), data[1:]

def send_framed_msg(sock, flag, payload):
    """ Sends a framed message: 4-byte length + 1-byte flag + pickled payload """
    payload_bytes = pickle.dumps(payload)
    flag_byte = flag.encode('utf-8')
    msg = flag_byte + payload_bytes
    length_prefix = struct.pack("!I", len(msg))
    sock.sendall(length_prefix + msg)

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
        self.tcp_client = None
        self._connect_to_server()

    def _connect_to_server(self):
        if self.tcp_client is not None:
            try:
                self.tcp_client.close()
            except Exception:
                pass
        try:
            self.tcp_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_client.settimeout(2.0)
            self.tcp_client.connect((self.host_ip, self.server_port))
        except Exception as e:
            self.log.error(f"Wavemeter connection failed: {e}")
            self.tcp_client = None

    @QtCore.Slot()
    def loop_body(self):
        self.queryTimer.start(self.queryInterval)
        self.wavelengths = np.append(self.wavelengths, self.__get_wavelength())[-self.buffer_length:]

    @QtCore.Slot(str, str)
    def send_request(self, request, action=None):
        action = None if action == '' else action
        if self.tcp_client is None:
            self._connect_to_server()
            if self.tcp_client is None:
                return None
        
        try:
            send_framed_msg(self.tcp_client, 'q', request)
            flag, response_bytes = recv_framed_msg(self.tcp_client)
        except Exception as e:
            self.log.error(f"Wavemeter connection error: {e}, reconnecting...")
            self._connect_to_server()
            if self.tcp_client is None:
                return None
            try:
                send_framed_msg(self.tcp_client, 'q', request)
                flag, response_bytes = recv_framed_msg(self.tcp_client)
            except Exception as e:
                self.log.error(f"Wavemeter reconnection failed: {e}")
                return None
        
        if not flag:
            self.tcp_client = None
            return None
            
        response = pickle.loads(response_bytes)
        
        if flag == 'c':
            #get wavelength
            self.wlm_time = np.vstack((self.wlm_time, response))
            return response[0]
        elif flag == 'k':
            if action != None:
                send_framed_msg(self.tcp_client, 'a', action)
                # Wait for acknowledgment
                ack_flag, ack_bytes = recv_framed_msg(self.tcp_client)
                return pickle.loads(ack_bytes) if ack_flag else None
            else:
                self.log.error("Set action! ")
        elif flag == 'u':
            return response
    
    def on_deactivate(self):
        if self.tcp_client is not None:
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