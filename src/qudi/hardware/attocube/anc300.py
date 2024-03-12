import serial
from qudi.core.configoption import ConfigOption
from qudi.core.module import Base
import numpy as np
import time





class ANC300(Base):
    """
    Serial control of the ANC 300 attocube scanner
    """
    _address = ConfigOption('address', None, missing='warn')


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.EOL = "\r\n"

    def on_activate(self):
        self.port = serial.Serial(port = self._address, 
                            baudrate = 38400, 
                            bytesize = serial.EIGHTBITS, 
                            stopbits = serial.STOPBITS_ONE, 
                            timeout = 2, 
                            parity=serial.PARITY_NONE)
        # try opening the port
        self.portOK = False
        try:
            self.port.open()
            self.portOK = True
        except:
            self.port.close()
            #traceback.print_exc()  # print the exception
        
        # put laser in a consistent mode
        if self.portOK:
            self.port.write(("echo off" % self.EOL).encode())   # echo off
            time.sleep(0.1)
            self.port.write(("prompt off" % self.EOL).encode())   # prompt off
            time.sleep(0.1)
                
            # clear input buffer so ready to talk to laser
            self.port.flushInput()
        
        self.portOpen()

    def on_deactivate(self):
        self.shutdown()

    def portPause(self, pause=.1):
        """ Pause before querying the port.
        """
        if self.portOK:
            time.sleep(pause)
    
    def portClear(self):
        """ Clear the input buffer.  The Verdi sends back an EOL
            if it received the message successfully.  They can
            build up in the buffer, so when you read from the port,
            you get this information, and now what you wanted.  It is
            also good to not oversample the port.
        """
        if self.portOK:
            self.port.flushInput()
    
    def portClose(self):
        """ Close the port.
        """
        if self.portOK:
            self.port.close()
            self.portPause()
            self.portOK = False
    
    def portOpen(self):
        """ Open the port.
        """
        self.portOK = False
        try:
            self.port.open()
            self.portOK = True
        except:
            print("The iBeam smart port did not ope4n")
            print("Please check the connection")
            self.port.close()
            #traceback.print_exc()  # print the exception

    def get_axis_output_voltage(self, axis=1):
        self.portClear()
        self.port.write((f"geto {axis}\r\n").encode())
        info = b""
        for line in self.port.readlines():
            print(line)
            info += line
        return info
    
    def inWaiting(self):
        """ See how many characters are input buffer.
        """
        if self.portOK:
            return self.port.inWaiting()

    def shutdown(self):
        """ Shutdown the laser and port.
        """
        if self.portOK:
            self.portClear()
            # self.ground_the_scanners()
            self.port.close()
            self.portOK = False

    def ground_the_scanners(self):
        """ ENABLE the laser.
        """
        if self.portOK:
            for i in range(3):
                self.port.write((f"setdci {i+1} off{self.EOL}").encode()) #set dc off
            return self.port.readline()

    def enable_the_scanners(self):
        """ ENABLE the laser.
        """
        if self.portOK:
            for i in range(3):
                self.port.write((f"setdci {i+1} on{self.EOL}").encode()) #set dc off
            return self.port.readline()
