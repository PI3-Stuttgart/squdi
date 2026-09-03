from os.path import join, getsize, isfile
import numpy as np
from TimeTagger import createTimeTagger,createTimeTaggerNetwork,AccessMode, Dump, GatedChannelInitial, Correlation, Histogram, Counter, CountBetweenMarkers, FileWriter, Countrate, Combiner, TimeDifferences, GatedChannel, DelayedChannel, freeTimeTagger
from qudi.core.configoption import ConfigOption
from qudi.core.module import Base


class TT(Base):
    _serial = ConfigOption('serial', None, missing='info')
    _hist = ConfigOption('hist', dict(), missing='warn')
    _corr = ConfigOption('corr', dict(), missing='warn')
    _time_differences = ConfigOption('time_differences', dict(), missing='warn')
    _count_between_markers = ConfigOption('count_between_markers', dict(), missing='warn')
    _counter = ConfigOption('counter', dict(), missing='warn')
    _combiner = ConfigOption('combiner', dict(), missing='warn')
    _channels_params = ConfigOption('channels_params', dict(), missing='info')
    _remote_tagger_ip = ConfigOption('remote_tagger_ip', None, missing='info')
    _remote_tagger_port = ConfigOption('remote_tagger_port', None, missing='info')
    _port = ConfigOption('port', 41101, missing='info')
    _remote_channel = ConfigOption('remote_tagger_port', None, missing='info')
    set_conditional_filter = True
    gated_vch = None
    gated_ref_vch = None
    """
    Example config.

    tagger:
        module.Class: 'swabian_instruments.timetagger_api.TT'
        counter:
            channels: [1,2]
            bin_width: 1000000000000
            n_values: 100

        hist:
            channels: [1, 2, 3]
            trigger_channel: 5
            bins_width: 1000
            number_of_bins: 500

        corr:
            channel_start: 1
            channel_stop: 2
            bin_width: 1000
            number_of_bins: 1000
            
        time_differences:
            channels: [1, 2, 3]
            start_channel: 5
            next_channel: 8
            n_histograms: 1

        combiner:
            channels: [1,2]

        test_channels: [] #[1,2,3,4,5,6,7]#[1,2, 4, -4]

        channels_params:
            6: # cwave internal scanner
                delay: 0
                trigger_level: 3
        """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sample_rate = 50
        self._time_diff_sum_start = 0  # ns
        self._time_diff_sum_stop = 100000  # ns

        self._time_diff_ref_start = 5000  # ns
        self._time_diff_ref_stop = 60000  # ns

        self._delay_diff_start = 0  # ns
        self._delay_diff_stop = 100000  # ns
        
        self.gated_counter_countbetweenmarkers = None

    @property
    def time_diff_sum_start(self):
        return self._time_diff_sum_start

    @time_diff_sum_start.setter
    def time_diff_sum_start(self, value):
        # Calculate the difference between new and old value
        self._delay_diff_start = value - self._time_diff_sum_start
        # Update the value
        self._time_diff_sum_start = value

        self.gate_start_vch = self.delayed_channel(self._hist['trigger_channel'], int(value * 1e3))
       

    @property
    def time_diff_sum_stop(self):
        return self._time_diff_sum_stop

    @time_diff_sum_stop.setter
    def time_diff_sum_stop(self, value):
        # Calculate the difference between new and old value
        self._delay_diff_stop = value - self._time_diff_sum_stop
        # Update the value
        self._time_diff_sum_stop = value

        self.gate_stop_vch = self.delayed_channel(self._hist['trigger_channel'], int(value * 1e3))

        self.gated_vch = self.gated_channel(signal_channel = 1, 
                                            gate_start_channel = self.gate_start_vch.getChannel(),
                                            gate_stop_channel = self.gate_stop_vch.getChannel(),
                                            )
                                            
    @property
    def time_diff_ref_start(self):
        return self._time_diff_ref_start

    @time_diff_ref_start.setter
    def time_diff_ref_start(self, value):
        self._time_diff_ref_start = value
        self.gate_ref_start_vch = self.delayed_channel(self._hist['trigger_channel'], int(value * 1e3))

    @property
    def time_diff_ref_stop(self):
        return self._time_diff_ref_stop

    @time_diff_ref_stop.setter
    def time_diff_ref_stop(self, value):
        self._time_diff_ref_stop = value
        self.gate_ref_stop_vch = self.delayed_channel(self._hist['trigger_channel'], int(value * 1e3))
        self.gated_ref_vch = self.gated_channel(signal_channel=1,
                                                gate_start_channel=self.gate_ref_start_vch.getChannel(),
                                                gate_stop_channel=self.gate_ref_stop_vch.getChannel())

    @property
    def delay_diff_start(self):
        return self._delay_diff_start

    @property
    def delay_diff_stop(self):
        return self._delay_diff_stop

    def release_resources(self):
        freeTimeTagger(self.tagger)


    def on_activate(self):
        try:
            if self._remote_tagger_ip is not None:
                self.tagger = createTimeTaggerNetwork(f'{self._remote_tagger_ip}:{self._remote_tagger_port}')
            else:
                if self._serial is not None:
                    self.tagger = createTimeTagger(self._serial)
                else:
                    self.tagger = createTimeTagger()
                self.tagger.startServer(access_mode = AccessMode.Control,port=self._port)
                self.log.info(f"Tagger initialization successful: {self.tagger.getSerial()}")


        except:
            self.log.error(f"\nCheck if the TimeTagger device is being used by another instance.")
            Exception(f"\nCheck if the TimeTagger device is being used by another instance.")


        self._constraints = {'hist':self._hist, 
                             'corr':self._corr, 
                             'counter': self._counter, 
                             'time_differences': self._time_differences}

        # set specified in the params.yaml channels params
        for channel, params in self._channels_params.items():
            channel = int(channel)
            if 'delay' in params.keys():
                self.delay_channel(delay=params['delay'], channel = channel)
            if 'trigger_level' in params.keys():
                self.tagger.setTriggerLevel(channel, params['trigger_level'])

        if self._hist != {}:
            # Virtual channels for signal gating
            self.gate_start_vch = self.delayed_channel(self._hist['trigger_channel'], int(self.time_diff_sum_start * 1e3))
            self.gate_stop_vch = self.delayed_channel(self._hist['trigger_channel'], int(self.time_diff_sum_stop * 1e3))
            self.gated_vch = self.gated_channel(signal_channel = 1, 
                                            gate_start_channel = self.gate_start_vch.getChannel(),
                                            gate_stop_channel = self.gate_stop_vch.getChannel())
            
            # Virtual channels for reference gating
            self.gate_ref_start_vch = self.delayed_channel(self._hist['trigger_channel'], int(self.time_diff_ref_start * 1e3))
            self.gate_ref_stop_vch = self.delayed_channel(self._hist['trigger_channel'], int(self.time_diff_ref_stop * 1e3))
            self.gated_ref_vch = self.gated_channel(signal_channel=1,
                                                   gate_start_channel=self.gate_ref_start_vch.getChannel(),
                                                   gate_stop_channel=self.gate_ref_stop_vch.getChannel())
        
        # if self.set_conditional_filter:
        #     self.tagger.setConditionalFilter(trigger=self._hist["channels"],
        #                                     filtered=self._hist["trigger_channel"])
        #if self._combiner["channels"] is not None:
        #    self._combined_channels = self.combiner(self._combiner["channels"])


    def on_deactivate(self):
        self.release_resources()

    #@remote_tagger
    def histogram(self, **kwargs):
        """
        The histogram takes default values from the params.yaml

        Besides, it is possible to set values:
        Example:
        channel=1, trigger_channel=5, bins_width=1000, numer_of_bins= 1000

        get data by hist.getData()
        """

        return Histogram(self.tagger,
                            kwargs['channel'],
                            kwargs['trigger_channel'],
                            kwargs['bin_width'],
                            kwargs['number_of_bins'])
    #@remote_tagger
    def correlation(self,  **kwargs):
        """
        The correlation takes default values from the params.yaml

        Besides, it is possible to set values:
        Example:
        channel_start=1, channel_stop=2, bins_width=1000, numer_of_bins= 1000

        get data by corr.getData()
        """


        return Correlation(self.tagger,
                            kwargs['channel_start'],
                            kwargs['channel_stop'],
                            kwargs['bin_width'],
                            kwargs['number_of_bins'])

    #FIX!
    #@remote_tagger
    def delay_channel(self, channel, delay):
        self.tagger.setInputDelay(delay=delay, channel=channel)
    
    def delayed_channel(self, signal_channel, delay):
       
        return DelayedChannel(
            tagger=self.tagger,
            input_channel=signal_channel,
            delay=delay
        )
    
    def gated_channel(self, signal_channel, gate_start_channel, gate_stop_channel, initial=GatedChannelInitial.Closed):
        """
        Creates a gated channel.

        Args:
            signal_channel (int): The channel to be gated.
            gate1_start_channel (int): The channel that starts the gate.
            gate1_stop_channel (int): The channel that stops the gate.
            initial (GatedChannelInitial): The initial state of the gate. Defaults to Closed.

        Returns:
            TimeTagger.GatedChannel: A GatedChannel object.
        """
        return GatedChannel(
            tagger=self.tagger,
            input_channel=signal_channel,
            gate_start_channel=gate_start_channel,
            gate_stop_channel=gate_stop_channel,
            initial=initial
        )

    

    def dump(self, dumpPath, filtered_channels=None):
        if filtered_channels != None:
            self.tagger.setConditionalFilter(filtered=[filtered_channels], trigger=self.apdChans)
        return Dump(self.tagger, dumpPath, self.maxDumps,\
                                    self.allChans)

    #@remote_tagger
    def countrate(self, channels=None):
        """
        The countrate takes default values from the params.yaml
        get data by ctrate.getData()
        """
        if channels == None:
            channels = self._counter['channels']
        return Countrate(self.tagger,
                                channels)

    #@remote_tagger
    def counter(self,**kwargs):
        """
        refresh_rate - number of samples per second:

        """
        return Counter(self.tagger,
                        kwargs['channels'],
                        kwargs['bin_width'],
                        kwargs['n_values'])

    #!FIX
    #@remote_tagger
    def combiner(self, channels):
        return Combiner(self.tagger, channels)

    #@remote_tagger
    def count_between_markers(self, click_channel, begin_channel, end_channel, n_values):

        return CountBetweenMarkers(self.tagger,
                                click_channel,
                                begin_channel,
                                end_channel,
                                n_values)

    def count_between_markers_nops(self, n_values=1):
        ## Adapted to work best with nuclear ops, might be rewritten with return statement, but takes time to see
        ## how it affects usage of the class.
        self.log.debug('Setting the gated counter with n values %s', n_values)
        self.log.debug('channels: start stop -- %s %s', self._count_between_markers['begin_channel'], self._count_between_markers['end_channel'])
        # TODO parse the channels from kwargs, otherwise if not present keep default.
        # something liek this.  cl_ch = getattr(kwargs['cl_ch'], self._click_channel)
        self.gated_counter_countbetweenmarkers = CountBetweenMarkers(self.tagger,
                                                                     click_channel=self._count_between_markers[
                                                                         'click_channel'],
                                                                     begin_channel=self._count_between_markers[
                                                                         'begin_channel'],
                                                                     end_channel=self._count_between_markers[
                                                                         'end_channel'],
                                                                     n_values=n_values)

    #@remote_tagger
    def time_differences(self, **kwargs):
        """
        The time_differences takes default values from the params.yaml
        get data by time_diff.getData()
        """
        return TimeDifferences(self.tagger,
                            click_channel=kwargs['click_channel'],
                            start_channel=kwargs['start_channel'],
                            next_channel=kwargs['next_channel'],
                            binwidth=kwargs['binwidth'],
                            n_bins=kwargs['n_bins'],
                            n_histograms=kwargs.get('n_histograms', 1))

    def write_into_file(self, filename, channels):
        return FileWriter(self.tagger,
        filename, channels)
