import numpy as np
from qtpy import QtCore
import inspect

from qudi.core.module import LogicBase
from qudi.core.connector import Connector

class MagnetLogic(LogicBase):
    ## connectors
    magnet = Connector(interface = 'magnet_3d')
    tagger = Connector(interface = 'TT')

    ## external signals
    sigScanFinished = QtCore.Signal()
    sigChangePswStatus = QtCore.Signal(int)
    sigPauseRamp = QtCore.Signal()
    sigContinueRamp = QtCore.Signal()
    sigRampToZero = QtCore.Signal()
    sigRamp = QtCore.Signal(np.ndarray,bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug = True
        self.abortScan = True


    def on_activate(self):
        self._magnet = self.magnet()
        self._tagger = self.tagger()

        # connect external signals
        self._magnet.sigRampFinished.connect(self._start_pixelIntegrationTimer)
        self.sigChangePswStatus.connect(self._magnet.set_psw_status)
        self.sigPauseRamp.connect(self._magnet.pause_ramp)
        self.sigContinueRamp.connect(self._magnet.continue_ramp)
        self.sigRampToZero.connect(self._magnet.ramp_to_zero)
        self.sigRamp.connect(self._magnet.ramp)

        # switches
        self._rampForPixel = False


    def on_deactivate(self):
        pass


    def set_up_scan(self, params, int_time):
        if self.debug:
            print('set_up_scan')
        self.abortScan = False
        self.int_time = int_time
        # set up counter
        self.set_up_counter(int_time)
        # build line for scanning
        self.scanning_line = self.build_3d_scan_line(params)
        # turn into list for more efficient memory usage
        self._scanning_line = list(self.scanning_line)
        # store counts in a list, convert to array once it is done
        self.counts = []
        # set up next pixel and start scan
        self._set_up_next_pixel()
        return


    def set_up_counter(self, int_time):
        """Sets up the counter for later count extraction.
        
        @param float int_time: integration time in ns.
        """
        if self.debug:
            print('set_up_counter')
        apdChannels = self._tagger._counter['channels']
        # convert ms into ps
        self.ctr = self._tagger.counter(bin_width=int(int_time*1e9),n_values=1,channels=apdChannels)

        self.pixelIntegrationTimer = QtCore.QTimer()
        self.pixelIntegrationTimer.setSingleShot(True)
        self.pixelIntegrationTimer.timeout.connect(self._scan_pixel, QtCore.Qt.QueuedConnection)
        # After setting up the counter, you need to wait at least one bin width, otherwise you get only zeros.
        # Setting up the counter takes a little bit less than 100 ns
        buffer = 100
        interval = int_time+buffer
        self.pixelIntegrationTimer.setInterval(interval)
        return


    def build_3d_scan_line(self, params):
        """ Buildas a 2d matrix to handle the 3d scan.

        @input array params: 2D array specifying the axes:
            [[axis0_start, axis0_stop, axis0_steps],
                [axis1_start, axis1_stop, axis1_steps],
                [axis2_start, axis2_stop, axis2_steps]]

        Each line is one pixel. 
        First axis 0 gets varied, then axis 1 and then axis 2.

        The resulting matrix looks like this:
        [   [x0,y0,z0],
            [x1,y0,z0],
            [x0,y1,z0],
            [x1,y1,z0],
            [x0,y2,z0],
            [x1,y2,z0],
            [x0,y0,z1],
            [x1,y0,z1],
            [x0,y1,z1],
            [x1,y1,z1],
            [x0,y2,z1],
            [x1,y2,z1]
        ]
        """
        if self.debug:
            print('build_3d_scan_line')
        # build axes
        axes = []
        for i in range(3):
            start,stop,steps = params[i,:]
            steps = int(steps)
            axis = np.linspace(start,stop,steps)
            axes.append(axis)
        axes = np.array(axes, dtype=object)
        # build matrix
        steps = params[:,2].astype(int)
        scanning_line = np.zeros((np.prod(steps),3))
        # ax0 into matrix
        ax0 = np.tile(axes[0],steps[1]*steps[2])
        scanning_line[:,0] = ax0
        # ax1 into matrix
        ax1 = np.tile(axes[1], (steps[0],1))
        ax1 = np.transpose(ax1)
        ax1 = np.reshape(ax1,steps[0]*steps[1])
        ax1 = np.tile(ax1, steps[2])
        scanning_line[:,1] = ax1
        # ax2 into matrix
        ax2 = np.tile(axes[2], (steps[0]*steps[1],1))
        ax2 = np.transpose(ax2)
        ax2 = np.reshape(ax2,np.prod(steps))
        scanning_line[:,2] = ax2
        if self.debug:
            print(f'scanning line is \n {scanning_line}')
        return scanning_line


    def _set_up_next_pixel(self):
        if self.debug:
            print('setting up next pixel')
        if self.abortScan:
            if self.debug:
                print('aborting scan')
            return
        if len(self._scanning_line) > 0: # if we still have pixels to scan
            self._rampForPixel = True # the ramp of the magnet was initiated by this script
            # choose next pixel
            self.pixel = self._scanning_line[0]
            if self.debug:
                print(f'current pixel is {self.pixel}')
            # remove the pixel from the stack
            self._scanning_line = self._scanning_line[1:]
            # turn spherical coordinates into carthesian
            carthesian = self.spherical_to_carthesian(self.pixel)
            if self.debug:
                print(carthesian)
            # ramp the magnet
            self.sigRamp.emit(carthesian,False)
            # self._magnet.ramp(field_target=carthesian, enter_persistent=False)
            return
        else: # if we are finished
            if self.debug:
                print('scan finished')
            # turn counts from list into array for faster processing later on
            self.counts = np.array(self.counts)
            self._rampForPixel = False
            del self.ctr
            self.sigScanFinished.emit()
            return


    def _start_pixelIntegrationTimer(self):
        if self.debug:
            print('_start_pixelIntegrationTimer')
        if self.abortScan:
            if self.debug:
                print('aborting scan')
            return
        if self._rampForPixel: # only do sth if ramp was initiated for the pixel
            if self.thread() is not QtCore.QThread.currentThread():
                if self.debug:
                    print('_start_pixelIntegrationTimer, thread is not currentThread')
                QtCore.QMetaObject.invokeMethod(self.pixelIntegrationTimer,
                                                'start',
                                                QtCore.Qt.BlockingQueuedConnection)
            else:
                if self.debug:
                    print('_start_pixelIntegrationTimer, thread is currentThread')
                self.pixelIntegrationTimer.start()
        else:
            if self.debug:
                print('ramp was not initiated by this file, doing noting.')


    @QtCore.Slot()
    def _scan_pixel(self):
        """ Gets counts and sets up next pixel.
        """
        if self.debug:
            print('_scan_pixel')
        if self.abortScan:
            if self.debug:
                print('aborting scan')
            return
        cts = self.ctr.getData()
        if self.debug:
            print(f'counts were {cts}')
        self.counts.append(cts) # store counts in list
        self._set_up_next_pixel()
        return


    def spherical_to_carthesian(self,spherical):
        """Turns spherical coordinates into carthesian coordinates.
        
        @param array spherical: spherical coordinates in [r, theta, phi]

        @return array carthesian: carthesian coordinates in [x, y, z]
        """
        if self.debug:
            print('spherical_to_carthesian')
        r = spherical[0]
        theta = spherical[1]
        phi = spherical[2]

        x = r*np.cos(phi)*np.sin(theta)
        y = r*np.sin(phi)*np.sin(theta)
        z = r*np.cos(theta)

        carthesian = np.array([x,y,z])

        return carthesian


    def stop_scan(self):
        """Aborts the scan.
        
        Also stops the ramp. Magnetic field will stay at the value it had when scan got aborted.
        """
        # stops execution of scan loop
        self.abortScan = True
        # pauses the magnet ramp
        self.sigPauseRamp.emit()
        # self._magnet.pause_ramp()
        return

    
    def set_psw_status(self,status):
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}: passing psw status {status}')
        self.sigChangePswStatus.emit(status)
        # self._magnet.set_psw_status(status)
        return


    def pause_ramp(self):
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        self.sigPauseRamp.emit()
        # self._magnet.pause_ramp()
        return


    def continue_ramp(self):
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        self.sigContinueRamp.emit()
        # self._magnet.continue_ramp()
        return

    
    def ramp_to_zero(self):
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        self.sigRampToZero.emit()
        # self._magnet.ramp_to_zero()
        return


    def ramp(self,axes):
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        self.sigRamp.emit(axes,False)
        # self._magnet.ramp(field_target=axes)
        return



    # -------------------------------------------------------------------------------
    # code that I wrote thinking it will be useful but was not.
    # Keeping it in case I need it lateron


    # def build_scanning_matrix(self, params):
    #     """Builds 4D-matrix for scanning along three axes.
        
    #     @input array params: 2D array specifying the axes:
    #         [[axis0_start, axis0_stop, axis0_steps],
    #             [axis1_start, axis1_stop, axis1_steps],
    #             [axis2_start, axis2_stop, axis2_steps]]

    #     first three indices are axes, last index is pixel.
    #     Example for scan in x y and z
    #     [
    #         [   [[x0,y0,z0],[x0,y0,z1]],
    #             [[x0,y1,z0],[x0,y1,z1]],
    #             [[x0,y2,z0],[x0,y2,z1]]
    #         ],
    #         [   [[x1,y0,z0],[x1,y0,z1]],
    #             [[x1,y1,z0],[x1,y1,z1]],
    #             [[x1,y2,z0],[x1,y2,z1]]
    #         ]
    #     ]
    #     Most inner block (axes 0 to 2) is last index, second most inner block ist third axis,
    #     outer block ist first axis. 
    #     To scan the first axis, you need to vary the first index,
    #     to scan the second axis you need to vary the second index
    #     and to scan the third axis you need to vary the third index.
    #     """
    #     # create axes
    #     axes = []
    #     for i in range(3):
    #         start,stop,steps = params[i,:]
    #         steps = int(steps)
    #         axis = np.linspace(start,stop,steps)
    #         axes.append(axis)
    #     axes = np.array(axes, dtype=object)
    #     # figure out dimension of each axis 
    #     dims = [len(ax) for ax in axes]
    #     dims.append(3)
    #     # built scanning matrix
    #     scanning_matrix = np.zeros(dims)
    #     ax = 0
    #     reps = [dims[2],dims[1],1]
    #     scanning_matrix[:,:,:,ax] = np.transpose(np.tile(axes[ax],reps),(2,1,0))
    #     ax = 1
    #     reps = [dims[2],dims[0],1]
    #     scanning_matrix[:,:,:,ax] = np.transpose(np.tile(axes[ax],reps),(1,2,0))
    #     ax = 2
    #     reps = [dims[0], dims[1], 1]
    #     scanning_matrix[:,:,:,ax] = np.transpose(np.tile(axes[ax],reps),(0,1,2))
    #     return scanning_matrix


    # def scan_along_matrix(self, scanning_matrix):
    #     # ramp field
    #     # once done (signal) take counts for XY seconds
    #     # ramp field again
    #     print(f'scanning along the following matrix: {scanning_matrix}')
    #     pass