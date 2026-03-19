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

def init_state_drive(state):
    '''
    State could be "p(m)3(1)2+(-,n)", example m32+, or p32-, p32n
    '''
    mw_init32R2 = 0
    mw_init32R1 = 0
    mw_init32m = 0
    RF_init12p = 0
    RF_init12m = 0
    ## MW drive
    if 'p' in state:
        if '+' in state:
            RF_init12m = 0.1
            #RF_init12p = 0.1
            mw_init32R2 = 0.08
            mw_init32m = 0.4
        elif '-' in state:
            RF_init12m = 0.1
            #RF_init12p = 0.1
            mw_init32R1 = 0.08
            mw_init32m = 0.0
    elif 'm' in state:
        mw_init32R2 = 0.07
        mw_init32R1 = 0.07

    pd2g1 = {
        'type': 'sine',
        'phases': [0],
        'amplitudes': [
            mw_init32R2,
            mw_init32R1,
            mw_init32m,
            mw_init32m,
            RF_init12p,
            RF_init12m],
        # 'frequencies':[30.5,38.5],
        'frequencies': [175.65, 177.9, 30.5, 38.5, 3.4, 6.47]
    }

    return pd2g1

def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name = None):
        sequence_name = 'Electron_rabi_test' if sequence_name is None else sequence_name
        mcas = MultiChSeq(name=sequence_name, ch_dict={'2g': [1, 2], 'ps': [1]})
        
        for idx, _I_ in current_iterator_df.iterrows():
            ### REPUMP ###
            mcas.start_new_segment('repump')
            mcas.asc(length_mus=100.0 , repump=True, name='Repump')
            mcas.start_new_segment('repump_decay')
            mcas.asc(length_mus=5.0)

            ### INIT ###
            # TIMING PROBLEM WITH A1 LASER AND REPUMP. THEY CANNOT BE LOOPED
            loops = 1
            mcas.start_new_segment(name='init', loop_count = loops)
            mcas.asc(
                A1= 'A1' in _I_['init'],
                A2 = 'A2' in _I_['init'],
                length_mus=E.round_length_mus_full_sample(_I_['init_time']/(64*loops))*64, 
                name='resonant_init',
                pd2g1 = init_state_drive('m')
            )
            
            mcas.start_new_segment(name='sequence')
            mcas.asc(length_mus=E.round_length_mus_full_sample(5.0), name='sequence wait 1')

            ### SEQUENCE ###
            amp_L = self.queue.tt.rp('e_rabi_ou350deg-90-L', omega=_I_['omega']).amp
            pi_L = self.queue.tt.rp('e_rabi_ou350deg-90-L', omega=_I_['omega']).pi
            pi_L = E.round_length_mus_full_sample(pi_L)
            sna.electron_rabi(
                mcas,
                new_segment=False,
                length_mus= pi_L,
                amplitudes=[amp_L],
                frequencies=[_I_['cnot_freq']],
                mixer_deg=[-90]
            )

            ### READOUT ###
            if _I_['init'] == 'A2':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=[30.0], wait_dur=0.0, robust=False,
                    nuc='ple_A2', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=0.5)
            elif _I_['init'] == 'A1':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=[30.0], wait_dur=0.0, robust=False,
                    nuc='ple_A1', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=0.5)
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

    nuclear.ple_refocus_interval = 400
    nuclear.confocal_refocus_interval = 600  # seconds
    nuclear.odmr_refocus_interval= 600

    #rabi refocus ?

    nuclear.queue._gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue._gated_counter.trace.average_results = False

    nuclear.parameters = OrderedDict(
        (
            ('omega', [0.25]), #for odmr probing 
            ('sweeps', range(200)),
            ('A2_power',[3]),
            #('init_time', [100]),
            #('init', ['A2']),
            ('init_time', [100, 5]),
            ('init', ['A1','A2']),
            #('readout', ['A1','A2']),
            ('cnot_freq',np.linspace(33,40,90)),
        )
    )
    #nuclear.number_of_simultaneous_measurements =  1*len(nuclear.parameters['mw_freq'])
    nuclear.number_of_simultaneous_measurements =  len(nuclear.parameters['cnot_freq'])

def run_fun(abort, **kwargs):
    print(1,' Nuclear started!!!')
    nuclear.queue = kwargs['queue']
    nuclear.queue._gated_counter.readout_duration = 60*1e6 # --> nvalues.
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print('run_fun started')
    nuclear.run(abort)