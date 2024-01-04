
from os.path import join, getsize, isfile
import numpy as np
from TimeTagger import createTimeTagger,createTimeTaggerNetwork,AccessMode, Dump, Correlation, Histogram, Counter, CountBetweenMarkers, FileWriter, Countrate, Combiner, TimeDifferences
from qudi.core.configoption import ConfigOption
from qudi.core.module import Base


class TT(Base):
    _serial = ConfigOption('serial', None, missing='info')
    _hist = ConfigOption('hist', dict(), missing='warn')
    _corr = ConfigOption('corr', dict(), missing='warn')
    _counter = ConfigOption('counter', dict(), missing='warn')
    _combiner = ConfigOption('combiner', dict(), missing='warn')
    _channels_params = ConfigOption('channels_params', dict(), missing='info')
    _remote_tagger_ip = ConfigOption('remote_tagger_ip', None, missing='info')
    _remote_tagger_port = ConfigOption('remote_tagger_port', None, missing='info')
    _port = ConfigOption('port', 12233, missing='info')
    _remote_channel = ConfigOption('remote_tagger_port', None, missing='info')
    set_conditional_filter = True

    """
    Example config.

    tagger:
        module.Class: 'swabian_instruments.timetagger_api.TT'
        counter:
            channels: [1,2]
            bin_width: 1000000000000
            n_values: 100

        hist:
            channel: 2
            trigger_channel: 5
            bins_width: 1000
            number_of_bins: 500

        corr:
            channel_start: 1
            channel_stop: 2
            bin_width: 1000
            number_of_bins: 1000

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
             
        
        self._constraints = {'hist':self._hist, 'corr':self._corr, 'counter': self._counter}

        # set specified in the params.yaml channels params
        for channel, params in self._channels_params.items():
            channel = int(channel)
            if 'delay' in params.keys():
                self.delay_channel(delay=params['delay'], channel = channel)
            if 'trigger_level' in params.keys():
                self.tagger.setTriggerLevel(channel, params['trigger_level'])
            
        # if self.set_conditional_filter:
        #     self.tagger.setConditionalFilter(trigger=self._hist["channels"], 
        #                                     filtered=self._hist["trigger_channel"])
        #if self._combiner["channels"] is not None:
        #    self._combined_channels = self.combiner(self._combiner["channels"])
        

    def on_deactivate(self):
        pass
        
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

    #@remote_tagger
    def time_differences(self, click_channel, start_channel,
                        next_channel, 
                        binwidth,n_bins, n_histograms):
    
        return TimeDifferences(self.tagger, 
                            click_channel=click_channel,
                            start_channel=start_channel,
                            next_channel=next_channel,
                            binwidth=binwidth,
                            n_bins=n_bins,
                            n_histograms=n_histograms)

    def write_into_file(self, filename, channels):
        return FileWriter(self.tagger,
        filename, channels)

    
