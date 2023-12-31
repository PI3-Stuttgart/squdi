# -*- coding: utf-8 -*-

"""
A hardware module for communicating with the fast counter FPGA.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

import os
import sys
import numpy as np

from qudi.core.configoption import ConfigOption
from qudi.interface.fast_counter_interface import FastCounterInterface


class FastCounterFGAPiP3(FastCounterInterface):
    """ Qudi module for the an FPGA based FastCounter.

    Example config for copy-paste:

    fpga_pi3:
        module.Class: 'fpga_fastcounter.fast_counter_fpga_pi3.FastCounterFGAPiP3'
        options:
            counter_package_path: C:\Software\qudi-iqo-thirdparty
            fpgacounter_serial: '143400058N'
            fpgacounter_channel_apd_0: 1
            fpgacounter_channel_apd_1: 3
            fpgacounter_channel_detect: 2
            fpgacounter_channel_sequence: 6

    """

    # config options
    _package_path = ConfigOption('counter_package_path', missing='error')
    _fpgacounter_serial = ConfigOption('fpgacounter_serial', missing='error')
    _channel_apd_0 = ConfigOption('fpgacounter_channel_apd_0', 1, missing='warn')
    _channel_apd_1 = ConfigOption('fpgacounter_channel_apd_1', 3, missing='warn')
    _channel_detect = ConfigOption('fpgacounter_channel_detect', 2, missing='warn')
    _channel_sequence = ConfigOption('fpgacounter_channel_sequence', 6, missing='warn')

    def on_activate(self):
        """ Connect and configure the access to the FPGA.
        """
        sys.path.append(self._package_path)
        try:
            import stuttgart_counter.TimeTagger as tt
            self._tt = tt
        finally:
            sys.path.remove(self._package_path)
        self._tt._Tagger_setSerial(self._fpgacounter_serial)
        bitfilepath = os.path.join(self._package_path, 'stuttgart_counter', 'TimeTaggerController.bit')
        self._tt._Tagger_setBitfilePath(bitfilepath)

        self._number_of_gates = int(100)
        self._bin_width = 1
        self._record_length = int(4000)

        self.configure(
            self._bin_width * 1e-9,
            self._record_length * 1e-9,
            self._number_of_gates)

        self.statusvar = 0

    def get_constraints(self):
        """ Retrieve the hardware constrains from the Fast counting device.

        @return dict: dict with keys being the constraint names as string and
                      items are the definition for the constaints.

         The keys of the returned dictionary are the str name for the constraints
        (which are set in this method).

                    NO OTHER KEYS SHOULD BE INVENTED!

        If you are not sure about the meaning, look in other hardware files to
        get an impression. If still additional constraints are needed, then they
        have to be added to all files containing this interface.

        The items of the keys are again dictionaries which have the generic
        dictionary form:
            {'min': <value>,
             'max': <value>,
             'step': <value>,
             'unit': '<value>'}

        Only the key 'hardware_binwidth_list' differs, since they
        contain the list of possible binwidths.

        If the constraints cannot be set in the fast counting hardware then
        write just zero to each key of the generic dicts.
        Note that there is a difference between float input (0.0) and
        integer input (0), because some logic modules might rely on that
        distinction.

        ALL THE PRESENT KEYS OF THE CONSTRAINTS DICT MUST BE ASSIGNED!
        """

        constraints = dict()

        # the unit of those entries are seconds per bin. In order to get the
        # current binwidth in seonds use the get_binwidth method.
        constraints['hardware_binwidth_list'] = [1 / 1000e6]

        # TODO: think maybe about a software_binwidth_list, which will
        #      postprocess the obtained counts. These bins must be integer
        #      multiples of the current hardware_binwidth

        return constraints

    def on_deactivate(self):
        """ Deactivate the FPGA.
        """
        if self.module_state() == 'locked':
            self.pulsed.stop()
        self.pulsed.clear()
        self.pulsed = None

    def configure(self, bin_width_s, record_length_s, number_of_gates=0):

        """ Configuration of the fast counter.

        @param float bin_width_s: Length of a single time bin in the time trace
                                  histogram in seconds.
        @param float record_length_s: Total length of the timetrace/each single
                                      gate in seconds.
        @param int number_of_gates: optional, number of gates in the pulse
                                    sequence. Ignore for not gated counter.

        @return tuple(binwidth_s, gate_length_s, number_of_gates):
                    binwidth_s: float the actual set binwidth in seconds
                    gate_length_s: the actual set gate length in seconds
                    number_of_gates: the number of gated, which are accepted
        """
        self._number_of_gates = number_of_gates
        self._bin_width = bin_width_s * 1e9
        self._record_length = int(record_length_s / bin_width_s)
        self.statusvar = 1

        self.pulsed = self._tt.Pulsed(
            self._record_length,
            int(np.round(self._bin_width*1000)),
            self._number_of_gates,
            self._channel_apd_0,
            self._channel_detect,
            self._channel_sequence
        )
        return bin_width_s, record_length_s, number_of_gates

    def start_measure(self):
        """ Start the fast counter. """
        self.module_state.lock()
        self.pulsed.clear()
        self.pulsed.start()
        self.statusvar = 2
        return 0

    def stop_measure(self):
        """ Stop the fast counter. """
        if self.module_state() == 'locked':
            self.pulsed.stop()
            self.module_state.unlock()
        self.statusvar = 1
        return 0

    def pause_measure(self):
        """ Pauses the current measurement.

        Fast counter must be initially in the run state to make it pause.
        """
        if self.module_state() == 'locked':
            self.pulsed.stop()
            self.statusvar = 3
        return 0

    def continue_measure(self):
        """ Continues the current measurement.

        If fast counter is in pause state, then fast counter will be continued.
        """
        if self.module_state() == 'locked':
            self.pulsed.start()
            self.statusvar = 2
        return 0

    def is_gated(self):
        """ Check the gated counting possibility.

        Boolean return value indicates if the fast counter is a gated counter
        (TRUE) or not (FALSE).
        """
        return True

    def get_data_trace(self):
        """ Polls the current timetrace data from the fast counter.

        @return numpy.array: 2 dimensional array of dtype = int64. This counter
                             is gated the the return array has the following
                             shape:
                                returnarray[gate_index, timebin_index]

        The binning, specified by calling configure() in forehand, must be taken
        care of in this hardware class. A possible overflow of the histogram
        bins must be caught here and taken care of.
        """
        info_dict = {'elapsed_sweeps': None,
                     'elapsed_time': None}  # TODO : implement that according to hardware capabilities
        return np.array(self.pulsed.getData(), dtype='int64'), info_dict


    def get_status(self):
        """ Receives the current status of the Fast Counter and outputs it as
            return value.

        0 = unconfigured
        1 = idle
        2 = running
        3 = paused
        -1 = error state
        """
        return self.statusvar

    def get_binwidth(self):
        """ Returns the width of a single timebin in the timetrace in seconds. """
        width_in_seconds = self._bin_width * 1e-9
        return width_in_seconds

