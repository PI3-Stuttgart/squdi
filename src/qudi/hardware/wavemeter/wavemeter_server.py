import socketserver
import struct
import pickle
import threading
import time
import numpy as np

# Try importing the high finesse API, but provide a dummy if not available
try:
    from qudi.hardware.wavemeter import high_finesse_api
except ImportError:
    class DummyWLM:
        def get_wavelength(self):
            return np.array([time.time(), 700.0 + np.random.rand()])
        def get_regulation_mode(self):
            return "auto"
        def get_reference_course(self):
            return "ok"
    class high_finesse_api:
        WLM = DummyWLM

def send_framed_msg(sock, flag, payload):
    """ Sends a framed message: 4-byte length + 1-byte flag + pickled payload """
    payload_bytes = pickle.dumps(payload)
    flag_byte = flag.encode('utf-8')
    msg = flag_byte + payload_bytes
    length_prefix = struct.pack("!I", len(msg))
    sock.sendall(length_prefix + msg)

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

class WavemeterRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            while True:
                flag, payload_bytes = recv_framed_msg(self.request)
                if not flag:
                    break # Client disconnected
                
                request_str = pickle.loads(payload_bytes)
                
                if request_str == "get_wavelengths":
                    # return shape (1, 2) array [time, wavelength]
                    val = self.server.wlm.get_wavelength()
                    # The client expects `response` to be np.array
                    send_framed_msg(self.request, 'c', val)
                
                elif request_str == "get_regulation_mode":
                    mode = self.server.wlm.get_regulation_mode()
                    send_framed_msg(self.request, 'u', mode)
                
                elif request_str == "set_regulation_mode":
                    # client expects 'k' flag to signal it should send the action
                    send_framed_msg(self.request, 'k', None)
                    action_flag, action_payload = recv_framed_msg(self.request)
                    action = pickle.loads(action_payload)
                    print(f"Setting regulation mode to: {action}")
                    # apply action logic here
                    send_framed_msg(self.request, 'u', "OK")

                elif request_str == "get_reference_course":
                    ref = self.server.wlm.get_reference_course()
                    send_framed_msg(self.request, 'u', ref)
                    
                else:
                    send_framed_msg(self.request, 'u', "Unknown Command")
                    
        except Exception as e:
            print(f"Connection error: {e}")

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

if __name__ == "__main__":
    HOST, PORT = "0.0.0.0", 1243

    # Instantiate Wavemeter
    wlm = high_finesse_api.WLM()

    server = ThreadedTCPServer((HOST, PORT), WavemeterRequestHandler)
    server.wlm = wlm
    server.allow_reuse_address = True
    
    print(f"Starting Robust Wavemeter Server on {HOST}:{PORT}...")
    server.serve_forever()
