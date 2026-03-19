# coding=utf-8
import datetime
import numpy as np
import os
import importlib
import notebooks.UserScripts.helpers.sequence_creation_helpers as sch; importlib.reload(sch)
import notebooks.UserScripts.helpers.shared as shared
from hardware.Keysight_AWG_M8190.pym8190a import MultiChSeq as MultiChSeq
import notebooks.UserScripts.helpers.snippets_awg as sna
importlib.reload(sna)
importlib.reload(shared)
#importlib.reload(MultiChSeq)
import notebooks.UserScripts.helpers.shared as ush;importlib.reload(ush)
from logic.qudip_enhanced import *
import hardware.Keysight_AWG_M8190.elements as E
from collections import OrderedDict


seq_name = os.path.basename(__file__).split('.')[0]
nuclear = sch.create_nuclear(__file__)
with open(os.path.abspath(__file__).split('.')[0] + ".py", 'r') as f:
    meas_code = f.read()

__TAU_HALF__ = 2*192/12e3
__SAMPLE_FREQUENCY__ = 12e3#e.__SAMPLE_FREQUENCY__

ael = 1.0

def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name = None):
        sequence_name = 'Electron_rabi_test' if sequence_name is None else sequence_name
        #print(self, current_iterator_df)
        
        #mcas = MultiChSeq(name=sequence_name, ch_dict={'2g': [1, 2], 'ps': [1]})
        #mcas.start_new_segment('start_sequence')
        mcas = MultiChSeq(name=sequence_name, ch_dict={'2g': [1, 2], 'ps': [1]})
        mcas.start_new_segment('start_sequence')
        mcas.asc(length_mus=5.0, repump=True, name='Repump')
        mcas.asc(length_mus=20.0)  # Starting... histogram 0
        for idx, _I_ in current_iterator_df.iterrows():
            mcas.asc(
                A1 = _I_['init']=='A1',
                A2 = _I_['init']=='A2', 
                length_mus=_I_['init_time'], 
                name='resonant_init',
                pd2g1 = {
                    'type':'sine',
                    'phases':[0],
                    'amplitudes':[_I_['mw_init']],#0.02
                    'frequencies':[177.8,168.4]
                })

            # Take care, that last thing on during init is the laser.
            mcas.asc(
                A1 = _I_['init']=='A1',
                A2 = _I_['init']=='A2', 
                length_mus=1.0, 
                name='resonant_init'
            )
            
            freq = [30.0]
            # SWAPPED READOUT AND INIT TO ALWAYS HAVE CONTRAST
            if _I_['init'] == 'A1':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=freq, wait_dur=_I_['wait_dur'], robust=False,
                    nuc='ple_A2_delay', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=_I_['laser_dur'])
            elif _I_['init'] == 'A2':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=freq, wait_dur=_I_['wait_dur'], robust=False,
                    nuc='ple_A1_delay', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=_I_['laser_dur'])
            mcas.asc(length_mus=0.5, name='sequence wait 2')

        self.queue._gated_counter.set_n_values(mcas, self.number_of_simultaneous_measurements) #how to get here the queue? readout duration/sequence length.

        return mcas
    return ret_mcas

def settings(pdc={}):
    ana_seq=[
        ['result', '>', 0, 1, 0, 1],
        #['result', '>', -1, 1, 0, 1],
        #['init', '>', -1, 1, 0, 1],
        # ['init', '>', 5, 1, 0, 1],
    ]
        #what does each entry do?
        # ana_seq[0]: ? 'result' or 'init', init - for postselection
        # ana_seq[1]: ? > or <
        # ana_seq[2]: "threshold"
        # ana_seq[3]: "nlp_per_point", number of laser pulses per point. N of repetitions. 
        # ana_seq[4]: set to 100 --> no counts measured; set to 7 --> counts can be measured; --> delta - exclusion zone. n > threshold +delta, or n< threhold - delta. 
        # ana_seq[5]: "number of results" --> ssr = cnot1 + laser1 + cnot2 + laser2, -> n=2, etc.. laser2-laser1,  histograms are centered around 0, 
    sch.settings(
        nuclear=nuclear,
        ret_mcas=ret_ret_mcas(pdc),
        analyze_sequence=ana_seq,
        pdc=pdc,
        meas_code=meas_code
    )

    nuclear.x_axis_title = 'Index'
    #nuclear.analyze_type = 'consecutive'
    # nuclear.analyze_type = 'standard'
    nuclear.analyze_type = 'average' #experimental feature for the fast 
    #nuclear.analyze_type = None
    nuclear.save_smartly = True

    #PLE refocus
    nuclear.do_ple_refocusA1 = False #not used 
    nuclear.do_ple_refocusA2 = True

    # ODMR refocus
    nuclear.refocus_cw_odmr = False
    nuclear.refocus_pulsed_odmr = False

    #confocal refocus
    nuclear.do_confocal_repump_refocus = False
    nuclear.do_confocal_A1A2_refocus = True
    nuclear.do_confocal_A2MW_refocus = False

    # Resonant Laser power
    nuclear.checkA1LaserPower = False # Not yet implemented in powerstablogic
    nuclear.checkA2LaserPower = False
    nuclear.A1LaserPower = 1 #nW
    nuclear.A2LaserPower = 3 #nW

    nuclear.ple_refocus_interval = 600
    nuclear.confocal_refocus_interval = 600  # seconds
    nuclear.odmr_refocus_interval= 600

    #rabi refocus ?

    nuclear.queue._gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue._gated_counter.trace.average_results = False

    nuclear.parameters = OrderedDict( # WHAT DOES ALL THIS MEAN ??? WHICH UNITS ??
        (
            ('A2_power',[3]),
            #('init', ['A2']),
            ('mw_init',[0.02]),
            ('sweeps', range(5)),
            ('init_time', [100]),
            ('laser_dur',E.round_length_mus_full_sample(np.linspace(0.05, .25, 5))),
            ('wait_dur',E.round_length_mus_full_sample(np.linspace(0.3, 0.6, 31))),
            ('init', ['A1', 'A2'])
            )
    )

    nuclear.number_of_simultaneous_measurements =  1

def run_fun(abort, **kwargs):
    print(1,' Nuclear started!!!')
    nuclear.queue = kwargs['queue']
    nuclear.queue._gated_counter.readout_duration = 3*1e6 # --> nvalues.
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print('run_fun started')
    nuclear.run(abort)