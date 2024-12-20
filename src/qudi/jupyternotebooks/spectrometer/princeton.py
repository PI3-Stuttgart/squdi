import numpy as np
from ctypes import *
import time

OPEN_EXCLUSIVE = 0

READOUT_NOT_ACTIVE = 0
EXPOSURE_IN_PROGRESS = 1
READOUT_IN_PROGRESS = 2
READOUT_COMPLETE = 3
FRAME_AVAILABLE = READOUT_COMPLETE
READOUT_FAILED = 4
ACQUISITION_IN_PROGRESS = 5
MAX_CAMERA_STATUS = 6

#*********************** Class 2: Data types ********************************/
# Data type used by pl_get_param with attribute type (ATTR_TYPE).           */
TYPE_CHAR_PTR     = 13
TYPE_INT8         = 12
TYPE_UNS8         =  5
TYPE_INT16        =  1
TYPE_UNS16        =  6
TYPE_INT32        =  2
TYPE_UNS32        =  7
TYPE_UNS64        =  8
TYPE_FLT64        =  4
TYPE_ENUM         =  9
TYPE_BOOLEAN      = 11
TYPE_VOID_PTR     = 14
TYPE_VOID_PTR_PTR = 15

# defines for classes                                                       */
CLASS0     = 0          # Camera Communications                      */
CLASS1     = 1          # Error Reporting                            */
CLASS2     = 2          # Configuration/Setup                        */
CLASS3     = 3          # Data Acuisition                            */
CLASS4     = 4          # Buffer Manipulation                        */

#*********************** Parameter IDs **************************************/
# Format: TTCCxxxx, where TT = Data type, CC = Class, xxxx = ID number      */


        # DEVICE DRIVER PARAMETERS (CLASS 0) */

#  Class 0 (next available index for class zero = 6) */

PARAM_DD_INFO_LENGTH        = ((CLASS0<<16) + (TYPE_INT16<<24) + 1)
PARAM_DD_VERSION            = ((CLASS0<<16) + (TYPE_UNS16<<24) + 2)
PARAM_DD_RETRIES            = ((CLASS0<<16) + (TYPE_UNS16<<24) + 3)
PARAM_DD_TIMEOUT            = ((CLASS0<<16) + (TYPE_UNS16<<24) + 4)
PARAM_DD_INFO               = ((CLASS0<<16) + (TYPE_CHAR_PTR<<24) + 5)

# Camera Parameters Class 2 variables */

# Class 2 (next available index for class two = 544) */

# Camera Type enum for PI cameras */

PARAM_CAMERA_TYPE           = ((CLASS2<<16) + (TYPE_INT32<<24)     + 350)

# Pixel Bias Correction Enable/Disable for Common Platform */
PARAM_PBC                   = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 351)

# SKIP_SREG_CLEAN */
PARAM_SKIP_SREG_CLEAN       = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 330)

# CCD skip parameters                                                       */
# Min Block. amount to group on the shift register, to through way.         */
PARAM_MIN_BLOCK             = ((CLASS2<<16) + (TYPE_INT16<<24)     +  60)
# number of min block groups to use before valid data.                      */
PARAM_NUM_MIN_BLOCK         = ((CLASS2<<16) + (TYPE_INT16<<24)     +  61)
# number of strips to clear at one time, before going to the                */
# minblk/numminblk scheme                                                   */
PARAM_SKIP_AT_ONCE_BLK      = ((CLASS2<<16) + (TYPE_INT32<<24)     + 536)
# Strips per clear. Used to define how many clears to use for continous     */
# clears and with clears to define the clear area at the beginning of an    */
# experiment.                                                               */
PARAM_NUM_OF_STRIPS_PER_CLR = ((CLASS2<<16) + (TYPE_INT16<<24)     +  98)
# Set Continuous Clears for Trenton Cameras. This is for clearing while     */
# in external trigger.                                                      */
PARAM_CONT_CLEARS           = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 540)   

# Clean while expose available for Common Platform cameras                  */
PARAM_CLN_WHILE_EXPO        = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 352)   

# PreExpose (actually after reading out) Cleans                             */
PARAM_PREEXP_CLEANS         = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 354)

# Only applies to Thompson ST133 5Mhz                                       */
# enables or disables anti-blooming.                                        */
PARAM_ANTI_BLOOMING         = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 293)

# This applies to ST133 1Mhz and 5Mhz and PentaMax V5 controllers. For the  */
# ST133 family this controls whether the BNC (not scan) is either not scan  */
# or shutter for the PentaMax V5, this can be not scan, shutter, not ready, */
# clearing, logic 0, logic 1, clearing, and not frame transfer image shift. */
# See enum below for possible values                                        */
PARAM_LOGIC_OUTPUT          = ((CLASS2<<16) + (TYPE_ENUM<<24)      +  66)

# Invert the LOGIC OUT signal                                               */
PARAM_LOGIC_OUTPUT_INVERT   = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 548)

# Edge Trigger defines whether the external sync trigger is positive or     */
# negitive edge active. This is for the ST133 family (1 and 5 Mhz) and      */
# PentaMax V5.0.                                                            */
# see enum below for possible values.                                       */
PARAM_EDGE_TRIGGER          = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 106)
# Intensifier gain is currently only used by the PI-Max and has a range of  */
# 0-255                                                                     */
PARAM_INTENSIFIER_GAIN      = ((CLASS2<<16) + (TYPE_INT16<<24)     + 216)

# Shutter, Gate, or Safe mode, for the PI-Max.                              */
PARAM_SHTR_GATE_MODE        = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 217)

# Installed Timing Generator's option board (enum OPTN_BD_SPEC)             */
PARAM_TG_OPTION_BD_TYPE     = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 353)

# ADC offset setting.                                                       */
PARAM_ADC_OFFSET            = ((CLASS2<<16) + (TYPE_INT16<<24)     + 195)
# CCD chip name.    */
PARAM_CHIP_NAME             = ((CLASS2<<16) + (TYPE_CHAR_PTR<<24)  + 129)

PARAM_COOLING_MODE          = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 214)
PARAM_HEAD_COOLING_CTRL     = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 338)
PARAM_COOLING_FAN_CTRL      = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 339)
PARAM_PREAMP_DELAY          = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 502)
PARAM_PREFLASH              = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 503)
PARAM_COLOR_MODE            = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 504)
PARAM_MPP_CAPABLE           = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 224)
PARAM_PREAMP_OFF_CONTROL    = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 507)
PARAM_SERIAL_NUM            = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 508)

# CCD Dimensions and physical characteristics                               */
# pre and post dummies of CCD.                                              */
PARAM_PREMASK               = ((CLASS2<<16) + (TYPE_UNS16<<24)     +  53)
PARAM_PRESCAN               = ((CLASS2<<16) + (TYPE_UNS16<<24)     +  55)
PARAM_POSTMASK              = ((CLASS2<<16) + (TYPE_UNS16<<24)     +  54)
PARAM_POSTSCAN              = ((CLASS2<<16) + (TYPE_UNS16<<24)     +  56)
PARAM_PIX_PAR_DIST          = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 500)
PARAM_PIX_PAR_SIZE          = ((CLASS2<<16) + (TYPE_UNS16<<24)     +  63)
PARAM_PIX_SER_DIST          = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 501)
PARAM_PIX_SER_SIZE          = ((CLASS2<<16) + (TYPE_UNS16<<24)     +  62)
PARAM_SUMMING_WELL          = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 505)
PARAM_FWELL_CAPACITY        = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 506)
# Y dimension of active area of CCD chip */
PARAM_PAR_SIZE              = ((CLASS2<<16) + (TYPE_UNS16<<24)     +  57)
# X dimension of active area of CCD chip */
PARAM_SER_SIZE              = ((CLASS2<<16) + (TYPE_UNS16<<24)     +  58)
# Can camera perform HW accumulation */
PARAM_ACCUM_CAPABLE         = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 538)


PARAM_FTSCAN                = ((CLASS2<<16) + (TYPE_UNS16<<24)     +  59) 

# customize chip dimension */
PARAM_CUSTOM_CHIP           = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   +  87)   

# customize chip timing */
PARAM_CUSTOM_TIMING         = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   +  88)
PARAM_PAR_SHIFT_TIME        = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 545)
PARAM_SER_SHIFT_TIME        = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 546)
PARAM_PAR_SHIFT_INDEX       = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 547)


# Kinetics Window Size */
PARAM_KIN_WIN_SIZE          = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 126)




# General parameters */
# Is the controller on and running? */
PARAM_CONTROLLER_ALIVE      = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 168)
# Readout time of current ROI, in ms */
PARAM_READOUT_TIME          = ((CLASS2<<16) + (TYPE_FLT64<<24)     + 179)





        # CAMERA PARAMETERS (CLASS 2) */

PARAM_CLEAR_CYCLES          = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 97)
PARAM_CLEAR_MODE            = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 523)
PARAM_FRAME_CAPABLE         = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 509)
PARAM_PMODE                 = ((CLASS2<<16) + (TYPE_ENUM <<24)     + 524)
PARAM_CCS_STATUS            = ((CLASS2<<16) + (TYPE_INT16<<24)     + 510)

# This is the actual temperature of the detector. This is only a get, not a */
# set                                                                       */
PARAM_TEMP                  = ((CLASS2<<16) + (TYPE_INT16<<24)     + 525)
# This is the desired temperature to set. */
PARAM_TEMP_SETPOINT         = ((CLASS2<<16) + (TYPE_INT16<<24)     + 526)
PARAM_CAM_FW_VERSION        = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 532)
PARAM_HEAD_SER_NUM_ALPHA    = ((CLASS2<<16) + (TYPE_CHAR_PTR<<24)  + 533)
PARAM_PCI_FW_VERSION        = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 534)
PARAM_CAM_FW_FULL_VERSION	= ((CLASS2<<16) + (TYPE_CHAR_PTR<<24)  + 534)

# Exsposure mode, timed strobed etc, etc */
PARAM_EXPOSURE_MODE         = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 535)

        # SPEED TABLE PARAMETERS (CLASS 2) */

PARAM_BIT_DEPTH             = ((CLASS2<<16) + (TYPE_INT16<<24)     + 511)
PARAM_GAIN_INDEX            = ((CLASS2<<16) + (TYPE_INT16<<24)     + 512)
PARAM_SPDTAB_INDEX          = ((CLASS2<<16) + (TYPE_INT16<<24)     + 513)
# define which port (amplifier on shift register) to use. */
PARAM_READOUT_PORT          = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 247)
PARAM_PIX_TIME              = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 516)

        # SHUTTER PARAMETERS (CLASS 2) */

PARAM_SHTR_CLOSE_DELAY      = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 519)
PARAM_SHTR_OPEN_DELAY       = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 520)
PARAM_SHTR_OPEN_MODE        = ((CLASS2<<16) + (TYPE_ENUM <<24)     + 521)
PARAM_SHTR_STATUS           = ((CLASS2<<16) + (TYPE_ENUM <<24)     + 522)
PARAM_SHTR_CLOSE_DELAY_UNIT = ((CLASS2<<16) + (TYPE_ENUM <<24)     + 543)
PARAM_SHTR_RES              = ((CLASS2<<16) + (TYPE_ENUM <<24)     + 343)


        # I/O PARAMETERS (CLASS 2) */

PARAM_IO_ADDR               = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 527)
PARAM_IO_TYPE               = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 528)
PARAM_IO_DIRECTION          = ((CLASS2<<16) + (TYPE_ENUM<<24)      + 529)
PARAM_IO_STATE              = ((CLASS2<<16) + (TYPE_FLT64<<24)     + 530)
PARAM_IO_BITDEPTH           = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 531)

        # DIAGNOSTIC PARAMETERS (CLASS 2) */
PARAM_DIAG                  = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 180)
PARAM_DIAG_P1               = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 181)
PARAM_DIAG_P2               = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 182)
PARAM_DIAG_P3               = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 183)
PARAM_DIAG_P4               = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 184)
PARAM_DIAG_P5               = ((CLASS2<<16) + (TYPE_UNS32<<24)     + 185)

        # GAIN MULTIPLIER PARAMETERS (CLASS 2) */

PARAM_GAIN_MULT_FACTOR      = ((CLASS2<<16) + (TYPE_UNS16<<24)     + 537)
PARAM_GAIN_MULT_ENABLE      = ((CLASS2<<16) + (TYPE_BOOLEAN<<24)   + 541)

# TTL Lines */
PARAM_TTL_LINES             = ((CLASS2<<16) + (TYPE_INT32<<24)     +  91)
PARAM_TTL_DIR_CTRL          = ((CLASS2<<16) + (TYPE_INT32<<24)     + 355)


        # ACQUISITION PARAMETERS (CLASS 3) */
        # (next available index for class three = 11) */

PARAM_EXP_TIME              = ((CLASS3<<16) + (TYPE_UNS16<<24)     +   1)
PARAM_EXP_RES               = ((CLASS3<<16) + (TYPE_ENUM<<24)      +   2)
PARAM_EXP_MIN_TIME          = ((CLASS3<<16) + (TYPE_FLT64<<24)     +   3)
PARAM_EXP_RES_INDEX         = ((CLASS3<<16) + (TYPE_UNS16<<24)     +   4)

        # PARAMETERS FOR  BEGIN and END of FRAME Interrupts */
PARAM_BOF_EOF_ENABLE        = ((CLASS3<<16) + (TYPE_ENUM<<24)      +   5)
PARAM_BOF_EOF_COUNT         = ((CLASS3<<16) + (TYPE_UNS32<<24)     +   6)
PARAM_BOF_EOF_CLR           = ((CLASS3<<16) + (TYPE_BOOLEAN<<24)   +   7)


# Test to see if hardware/software can perform circular buffer */
PARAM_CIRC_BUFFER           = ((CLASS3<<16) + (TYPE_BOOLEAN<<24)   + 299)

# Hardware Will Automatically Stop After A Specified Number of Frames */
PARAM_HW_AUTOSTOP           = ((CLASS3<<16) + (TYPE_INT16<<24)     + 166)
PARAM_HW_AUTOSTOP32         = ((CLASS3<<16) + (TYPE_INT32<<24)     + 166)




# #*********************** Class 2: Attribute IDs *****************************/
# #
  # Function: pl_get_param()
# */
# enum
# { ATTR_CURRENT, ATTR_COUNT, ATTR_TYPE, ATTR_MIN, ATTR_MAX, ATTR_DEFAULT,
  # ATTR_INCREMENT, ATTR_ACCESS, ATTR_AVAIL
# };

ATTR_CURRENT        = 0
ATTR_COUNT          = 1
ATTR_TYPE           = 2
ATTR_MIN            = 3
ATTR_MAX            = 4
ATTR_DEFAULT        = 5
ATTR_INCREMENT      = 6
ATTR_ACCESS         = 7
ATTR_AVAIL          = 8

INT_FLOAT_TYPES = {1:c_int16(),
                   2:c_int32(),
                   4:c_double(),
                   5:c_uint8(),
                   6:c_uint16(),
                   7:c_uint32(),
                   8:c_uint64(),
                   9:c_uint32(),
                   11:c_bool(),
                   12:c_int8(),
                   }

# #*********************** Class 2: Access types ******************************/
# #
  # Function: pl_get_param( ATTR_ACCESS )
# */
# enum
# { ACC_ERROR, ACC_READ_ONLY, ACC_READ_WRITE, ACC_EXIST_CHECK_ONLY,
  # ACC_WRITE_ONLY
# };


# enum
#{ TIMED_MODE, STROBED_MODE, BULB_MODE, TRIGGER_FIRST_MODE, FLASH_MODE,
#  VARIABLE_TIMED_MODE, INT_STROBE_MODE
#};

mode_map = {'TIMED':0, 'BULB':2}

c_uint16_p = POINTER(c_uint16)

dll=windll.LoadLibrary('C:\\WINDOWS\\system32\\pvcam64.dll')

def get_error():
    message = create_string_buffer(255)
    code = dll.pl_error_code()
    dll.pl_error_message(code , message)
    return code, message.value

def check(result):
    if not result:
        code, message = get_error()
        raise RuntimeError(('Error code %i: '%code) + message)
        
class Region(Structure):
    _fields_ = [('s1',   c_uint16),
                ('s2',   c_uint16),
                ('sbin', c_uint16),
                ('p1',   c_uint16),
                ('p2',   c_uint16),
                ('pbin', c_uint16),
                ]

class Camera(object):

    """
    Basic access to a princeton camera via pvcam32.dll and ctypes
    """
    
    def __init__(self):
        self.set_roi()
        self.set_exp_time()
        
    def __enter__(self):
        pass
        
    def __exit__(self, typ, val, traceback):
        self.close()
        
    def open(self):
        self.handle = c_int16()
        cam_name = create_string_buffer(255)
        if not dll.pl_pvcam_init():
            self.close()
            raise RuntimeError('could not initialize camera')
        if not dll.pl_cam_get_name(0, cam_name):
            self.close()
            raise RuntimeError('could not get camera name')
        self.cam_name = cam_name.value
        if not dll.pl_cam_open(cam_name, byref(self.handle), OPEN_EXCLUSIVE):
            self.close()
            raise RuntimeError('could not open camera')
        self.ping()
        self.set_param(PARAM_READOUT_PORT,1)
        self.set_param(PARAM_GAIN_INDEX,1)
        return self

    def ping(self):
        if not dll.pl_cam_get_diags(self.handle):
            code, message = get_error()
            raise RuntimeError(('Error code %i: '%code) + message)
        
    def close(self):
        try:
            dll.pl_cam_close(self.handle)
        finally:
            dll.pl_pvcam_uninit()
    
    def get_param(self, param_id):
        flag = c_int()
        check(dll.pl_get_param(self.handle,
                               c_uint32(param_id),
                               ATTR_AVAIL,
                               byref(flag))
                               )
        if not flag.value:
            raise ValueError('Attribute not available')
        typ = c_uint16()
        check(dll.pl_get_param(self.handle,
                               c_uint32(param_id),
                               ATTR_TYPE,
                               byref(typ)
                               ))
        ret = {}
        if typ.value == TYPE_ENUM:
            # see DisplayEnumInfo in pvcam27 manual
            count = c_uint32()
            check(dll.pl_get_param(self.handle,
                                    c_uint32(param_id),
                                    ATTR_COUNT, byref(count)
                                    ))
            value = c_uint32()
            name = create_string_buffer(100)
            for index in range(count.value):
                check(dll.pl_get_enum_param(self.handle, c_uint32(param_id), index, byref(value), name, 100))
                ret[name.value] = value.value
        if typ.value in INT_FLOAT_TYPES:
            # see DisplayFloatsIntsInfo in pvcam27 manual
            value = INT_FLOAT_TYPES[typ.value]
            for key, attr in [('CURRENT',ATTR_CURRENT), ('DEFAULT',ATTR_DEFAULT), ('MIN',ATTR_MIN), ('MAX',ATTR_MAX), ('INCREMENT',ATTR_INCREMENT)]:
                check(dll.pl_get_param(self.handle,
                                   c_uint32(param_id),
                                   attr,
                                   byref(value))
                                   )
                ret[key] = value.value
        else:
            raise TypeError('Type not supported')
        return ret

    def set_param(self, param_id, new):
        flag = c_int()
        check(dll.pl_get_param(self.handle,
                               c_uint32(param_id),
                               ATTR_AVAIL,
                               byref(flag))
                               )
        if not flag.value:
            raise ValueError('Attribute not available')
        typ = c_uint16()
        check(dll.pl_get_param(self.handle,
                               c_uint32(param_id),
                               ATTR_TYPE,
                               byref(typ)
                               ))
        if typ.value in INT_FLOAT_TYPES:
            # see DisplayFloatsIntsInfo in pvcam27 manual
            value = INT_FLOAT_TYPES[typ.value]
            value.value = new
            #value = np.array((new,),dtype=int)
            #print value
            check(dll.pl_set_param(self.handle,
                                   c_uint32(param_id),
                                   byref(value))
                               )
        else:
            raise TypeError('Type not supported')
        return
        
    # def acquire(self, poll_time=0.02):
        # self.start()
        # return self.retrieve(poll_time)

    def set_exp_time(self, exp_time=10000):
        self.exp_time = exp_time
        
    def get_exp_time(self):
        return self.exp_time
        
    def set_roi(self, roi={'s1':0,'s2':1339,'sbin':1,'p1':0,'p2':99,'pbin':1}):
        self.region = Region(**roi)
        
    def get_roi(self):
        return self.region
        
    def start_sequence(self, n_frames=1, mode='TIMED'):
        check(dll.pl_exp_init_seq())
        self.n_frames = n_frames
        self.size = c_uint32()
        check(dll.pl_exp_setup_seq(self.handle,
                                    c_uint16(self.n_frames),
                                    c_uint16(1),
                                    byref(self.region),
                                    c_int16(mode_map[mode]),
                                    c_uint32(self.exp_time),
                                    byref(self.size)))
        self.frames = np.empty((self.size.value,), dtype=np.uint16)
        #self.ping()
        check(dll.pl_exp_start_seq(self.handle, self.frames.ctypes.data_as(c_uint16_p)))
    
    def retrieve_sequence(self, poll_time=0.02):
        ret = 1
        status  = c_int16(READOUT_NOT_ACTIVE)
        dummy   = c_uint32()
        #self.ping()
        while ret and (status.value != READOUT_COMPLETE and status.value != READOUT_FAILED):
            time.sleep(poll_time)
            ret = dll.pl_exp_check_status(self.handle, byref(status), byref(dummy))
        if not ret:
            raise RuntimeError('Failed to check camera status')
        if status.value == READOUT_FAILED:
            raise RuntimeError('Failed to read from camera. Error code: %i', dll.pl_error_code() )
        s_pixels = (self.region.s2 - self.region.s1 + 1) / self.region.sbin
        p_pixels = (self.region.p2 - self.region.p1 + 1) / self.region.pbin
        return self.frames[:self.size.value/2].reshape((self.n_frames,p_pixels,s_pixels))
        #return self.frames
        #return self.frames[:self.size.value/2].reshape((self.n_frames,512,512))
    
    def uninit_sequence(self):
        check(dll.pl_exp_finish_seq(self.handle, self.frames.ctypes.data_as(c_uint16_p), 0))
        check(dll.pl_exp_uninit_seq())

import array
        
class Spectrometer(Camera):

    def __init__(self):
        super(Spectrometer, self).__init__()
        self.set_roi({'s1':0,'s2':1339,'sbin':1,'p1':0,'p2':99,'pbin':100})
        #self.load_calibration(wavelength)
        self.open()

    def shut_down(self):
        self.close()
    def load_calibration(self, filename):
        data = np.loadtxt(filename)
        self.wavelength = data[:,0]
        
    def get_spectrum(self):
        
        
        self.start_sequence()
        frames = self.retrieve_sequence()
        
        line = frames[0].mean(0)
        return line.tolist()
        
    def get_wavelength(self):
        return self.wavelength.tolist()
    
    def config_coolele(self):
        #configure to low noise read out port
        apfel=self.get_ReadoutPortParam()
        self.set_ReadoutPortParam(apfel['Low Noise'])
    
    def get_ReadoutPortParam(self):
        return self.get_param(PARAM_READOUT_PORT)

    def set_ReadoutPortParam(self,param):
        return self.set_param(PARAM_READOUT_PORT,param)
    
        
if __name__ == '__main__':
    
    spectrometer = Spectrometer('650.txt')
    
    #spectrometer.get_spectrum(exp_time=1000,roi=roi)
    
    #camera = Camera()
    
    #camera.open()
    #camera.start_sequence(exp_time=60000)
    
    #print camera.get_param(PARAM_PMODE)
    #camera.close()
    
    #camera.uninit_sequence()

    #pass
    # handle = c_int16()
    # dummy = c_int16()
    # cam_name = create_string_buffer(255)
    # print dll.pl_pvcam_init()
    # if not dll.pl_cam_get_total(byref(dummy)):
		# code, message = get_error()
		# raise RuntimeError(('Error code %i: '%code) + message)
    # else:
        # print dummy.value
    # print dll.pl_cam_get_name(0, cam_name)
    
    # self.cam_name = cam_name.value
        # if not dll.pl_cam_open(cam_name, byref(self.handle), OPEN_EXCLUSIVE):
            # self.close()
            # raise RuntimeError('could not open camera')
        # self.ping()
        # self.set_param(PARAM_READOUT_PORT,1)
        # self.set_param(PARAM_GAIN_INDEX,1)
        # return self

#    camera = Camera()
 
    # with camera.open():
        # for val in dir():
            # if 'PARAM_' in val:
                # try:
                    # par = camera.get_param(eval(val))
                    # #print val, par
                    # if 'CURRENT' in par and par['CURRENT'] != par['DEFAULT']:
                        # print val, par['DEFAULT'], par['CURRENT']
                # except:
                    # pass
                    # #print val, 'failed'

    # def test_acquisition():
        # with camera.open():
            # camera.init_sequence()
            # for i in range(10):
                # camera.start_sequence()
                # frame = camera.retrieve_sequence()
                # print frame[0].mean()           
            # camera.uninit_sequence()

    # def print_performance():
        # import cProfile
        # cProfile.run('test_acquisition()')

    # print_performance()
        
    # with camera.open():
        # print camera.get_param(PARAM_PMODE)
        
    # with camera.open():
        # camera.init_sequence()
        # camera.start_sequence()
        # frame = camera.retrieve_sequence()
        # print frame[0].mean()
        
    #camera.open()
    
    
    
    # for i in range(100):
        # value = camera.get_param(i)
        # print value
    #camera.close()


        #version = c_uint16()
        #check( dll.pl_pvcam_get_ver(byref(version)) )
        #print 'version:', version.value

    # def get_param(self, id):
        # count  = c_int16()
        # if not dll.pl_get_param(self.handle, c_uint32(id), ctypes.byref(count)):
            # print get_error()
    
    # def get_frame(self, exp_time=100):
        # size    = c_uint32()
        # status  = c_int16(READOUT_NOT_ACTIVE)
        # dummy   = c_uint32()
        # region  = Region(s1=c_uint16(0), s2=c_uint16(511), sbin=c_uint16(1), p1=c_uint16(0), p2=c_uint16(511), pbin=c_uint16(1))

        # check( dll.pl_exp_init_seq() )
        # check( dll.pl_exp_setup_seq(self.handle, 1, 1, byref(region), TIMED_MODE, c_uint32(exp_time), byref(size)) )
    
        # frame = np.empty((size.value,), dtype=np.uint16)

        # check( dll.pl_exp_start_seq(self.handle, frame.ctypes.data_as(c_uint16_p)) )
        # while dll.pl_exp_check_status(self.handle, byref(status), byref(dummy)) \
                # and (status.value != READOUT_COMPLETE and status.value != READOUT_FAILED):
            # time.sleep(0.1)
        # if status.value == READOUT_FAILED:
            # raise RuntimeError('Failed to read from camera. Error code: %i', dll.pl_error_code() )
        
        # check( dll.pl_exp_finish_seq(self.handle, frame.ctypes.data_as(c_uint16_p), 0) )
        # check( dll.pl_exp_uninit_seq() )
        # return frame[:size.value/2].reshape((512,512))




    
    #print dll.pl_pvcam_init()
    #print dll.pl_pvcam_uninit()

    #print dll.pl_pvcam_uninit()
    #print dll.pl_pvcam_uninit()
    # print 'init:', check( dll.pl_pvcam_init() )
    # handle = c_int16()
    # cam_name = create_string_buffer(32)
    # print 'get name:', check( dll.pl_cam_get_name(0, cam_name) )
    # print 'open:', check( dll.pl_cam_open(cam_name, byref(handle), 0) )
    # size    = c_uint32()
    # status  = c_int16(READOUT_NOT_ACTIVE)
    # dummy   = c_uint32()
    # region  = Region(s1=c_uint16(0), s2=c_uint16(511), sbin=c_uint16(1), p1=c_uint16(0), p2=c_uint16(0), pbin=c_uint16(1))

    # print 'init_seq:', check( dll.pl_exp_init_seq() )
    # print 'setup_seq:', check( dll.pl_exp_setup_seq(handle, 1, 1, byref(region), TIMED_MODE, 100, byref(size)) )
    # frame = np.zeros((size.value,),dtype=np.uint16)

    # import time
    # print 'start_seq', check( dll.pl_exp_start_seq(handle, frame.ctypes.data_as(c_uint16_p)) )
    # while dll.pl_exp_check_status(handle, byref(status), byref(dummy)) \
                # and (status.value != READOUT_COMPLETE and status.value != READOUT_FAILED):
        # time.sleep(0.1)
    # if status.value == READOUT_FAILED:
       # raise RuntimeError('Failed to read from camera. Error code: %i', dll.pl_error_code() )
        
    # print 'finish_seq:', check( dll.pl_exp_finish_seq(handle, frame.ctypes.data_as(c_uint16_p), 0) )
    # print 'uninit_seq:', check( dll.pl_exp_uninit_seq() )
    
    # print 'close:', check( dll.pl_cam_close(handle) )
    # print 'uninit:', check( dll.pl_pvcam_uninit() )
    
    #s=Spectrometer()
    