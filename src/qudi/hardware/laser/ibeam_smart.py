import time
import serial

from enum import Enum

from qudi.core.configoption import ConfigOption
from qudi.core.module import Base

ON  = 1
OFF = 0
EOL = "\r\n"

class iBeamSmart(Base):
    #TODO: add documentation here
    """
    """
    port = ConfigOption(name='port', missing='error')

    channel = 2
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        """ Initalize the verdieLaser object.
            
            It will grab the first available I/O serial port, as is
            consistent with the PySerial modules.
        """
        # configure the port
        pass


    def on_activate(self):
        """ Activate module.
        """
        self.port = serial.Serial(port = self.port, 
                                    baudrate = 115200, 
                                    bytesize = serial.EIGHTBITS, 
                                    stopbits = serial.STOPBITS_ONE, 
                                    timeout=5, 
                                    parity=serial.PARITY_NONE)

        
        # try opening the port
        self.portOK = False
        try:
            self.port.open()
            self.portOK = True
        except:
            print("The iBeam smart port did not open")
            print("Please check the connection")
            self.port.close()
            #traceback.print_exc()  # print the exception
        
        # put laser in a consistent mode
        if self.portOK:
            self.port.write(("echo off" % EOL).encode())   # echo off
            time.sleep(0.1)
            self.port.write(("prompt off" % EOL).encode())   # prompt off
            time.sleep(0.1)
                
            # clear input buffer so ready to talk to laser
            self.port.flushInput()
        
        self.portOpen()

    def on_deactivate(self):
        """ Deactivate module.
        """
        self.port.close()

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

    
    def inWaiting(self):
        """ See how many characters are input buffer.
        """
        if self.portOK:
            return self.port.inWaiting()
    
    #####
    def laserQuery(self, cmd):
        """ Submit a query to the Veri and return the value.
            It will try to get the return value 11 times, and
            if it fails, it will return the string '-999'.  If the
            port has an error (portOK != True), it returns '-888'
        """
        if self.portOK:
            cnt = 0
            while True:
                self.portClear()
                self.port.write(("?%s%s" % (cmd, EOL)).encode())
                self.portPause()
                returnVal = self.port.readline()[:-2]
                cnt += 1
                if str(returnVal[0]).isdigit():
                  # first letter is a digit, readline successful
                  break
                elif cnt > 10:
                  returnVal = '-999'
            return returnVal
        else:
            return '-888'
    #####
    
    def shutdown(self):
        """ Shutdown the laser and port.
        """
        if self.portOK:
            self.portClear()
            self.setShutter(0)
            self.portPause()
            self.setPower(0.01)
            self.portPause()
            self.port.close()
            self.portOK = False

    def enable(self):
        """ ENABLE the laser.
        """
        if self.portOK:
            self.port.write((f"en {self.channel}{EOL}").encode())
            
    def disable(self):
        """ Disable the laser.
        """
        if self.portOK:
            self.port.write((f"di {self.channel}{EOL}").encode())

    def getPower(self):
        """ Check the laser output power.
        """
        #TODO!
        return self.power
    
    def setPower(self, power):
        """ Set the laser output power in muW.
        """
        self.power = power
        if self.portOK:
            if power <= 0:
                power = 0.01
            elif power >= 100000:
                power = 100000
            self.port.write(f"ch pow {power} mic {EOL}".encode())
      
    
