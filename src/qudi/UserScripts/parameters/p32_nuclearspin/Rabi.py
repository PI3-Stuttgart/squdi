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


def init_state_drive(state, freqs):
    '''
    State could be "p(m)3(1)2+(-,n)", example m32+, or p32-, p32n 
    '''
    mw_init32L1 = 0
    mw_init32L2 = 0
    mw_init32R1 = 0
    mw_init32R2 = 0
    if 'p' in state:
            mw_init32L1 = 0.4
            mw_init32L2 = 0.4
    elif 'm' in state:
            mw_init32R1 = 0.4
            mw_init32R2 = 0.4
    pd2g1 = {
        'type':'sine',
        'phases':[0],
        'amplitudes':[
                    mw_init32L1,
                    mw_init32L2,
                    mw_init32R1,
                    mw_init32R2],     
        'frequencies':freqs
    }
    
    return pd2g1


def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name = None):
        sequence_name = 'Nuclear_rabi_test' if sequence_name is None else sequence_name
        
        mcas = MultiChSeq(name=sequence_name, ch_dict={'2g': [1, 2], 'ps': [1]})
        mcas.start_new_segment('start_sequence')
        for idx, _I_ in current_iterator_df.iterrows():
            ### REPUMP ###
            mcas.start_new_segment('start_sequence', loop_count=3)
            mcas.asc(length_mus=E.round_length_mus_to_x_multiple_ps(15.0), repump=True, name='Repump')
            mcas.start_new_segment('start_sequence_decay', loop_count=3)
            mcas.asc(length_mus=E.round_length_mus_to_x_multiple_ps(10.0))  #Decay from metastables.
            
            ### INITIALIZATION ###
            state = _I_['init_state']
            segment_length = 7
            loops, correction_mus = shared.calculate_loop_count(_I_['init_time'],segment_length)
            mcas.start_new_segment(name='init', loop_count = loops)
            mcas.asc(
                A1= '32' in state,
                A2 = '12' in state,
                gateMW = True,
                length_mus=E.round_length_mus_to_x_multiple_ps(segment_length), 
                name='resonant_init',
                pd2g1 = init_state_drive(state, [31.2, 39.24, 168.93, 178.35])
            ) 
            mcas.start_new_segment(name='init', loop_count = 1)
            mcas.asc(
                A1= '32' in state,
                A2 = '12' in state,
                length_mus=E.round_length_mus_to_x_multiple_ps(correction_mus), 
                name='resonant_init',
                pd2g1 = init_state_drive(state, [31.2, 39.24, 168.93, 178.35])
            )
            
            mcas.asc(length_mus=E.round_length_mus_to_x_multiple_ps(1.0), name='waitAfterInit')

            ### SEQUENCE ###
            L_pi_dur = self.queue.tt.rp('e_rabi_ou500deg-90-L', omega=_I_['omega']).pi
            C_pi_dur = self.queue.tt.rp('e_rabi_ou500deg-90-C', omega=_I_['omega']).pi
            R_pi_dur = self.queue.tt.rp('e_rabi_ou500deg-90-R', omega=_I_['omega']).pi
            L_amp = self.queue.tt.rp('e_rabi_ou500deg-90-L', omega=_I_['omega']).amp
            C_amp = self.queue.tt.rp('e_rabi_ou500deg-90-C', omega=_I_['omega']).amp
            R_amp = self.queue.tt.rp('e_rabi_ou500deg-90-R', omega=_I_['omega']).amp
            # Flip to +1/2            
            mcas.asc(length_mus=E.round_length_mus_to_x_multiple_ps(0.256), name='gateMW', gateMW = True)
            sna.electron_rabi(
                mcas,
                new_segment=False,
                gateMW = True,
                length_mus= C_pi_dur,
                amplitudes=[C_amp],
                frequencies=[108.6],
                mixer_deg=[-90]
            )
            # Flip to +3/2            
            sna.electron_rabi(
                mcas,
                new_segment=False,
                gateMW = True,
                length_mus= C_pi_dur,
                amplitudes=[C_amp],
                frequencies=[178.35],
                mixer_deg=[-90]
            )
            mcas.asc(length_mus=E.round_length_mus_to_x_multiple_ps(1.024), name='gateMW', gateMW = True)
            ### Nuclear Tau Pulse ###
            sna.electron_rabi(
                mcas,
                new_segment=False,
                gateMW = True,
                length_mus= _I_['tau_rabi'],
                amplitudes=[_I_['amp']],
                frequencies=[_I_['mw_freq']],
                mixer_deg=[-90]
            )
            mcas.asc(length_mus=E.round_length_mus_to_x_multiple_ps(1.024), name='gateMW', gateMW = True)
            
            ### Electron pi to project into m12 state ###

            sna.electron_rabi(
                mcas,
                new_segment=False,
                gateMW = True,
                length_mus= R_pi_dur,
                amplitudes=[R_amp],
                frequencies=[_I_['cnot_freq']],
                mixer_deg=[-90]
            )
            mcas.asc(length_mus=0.25, name='waitAfterMW')
            
            freq = [30.0]
            if _I_['readout'] == 'A2':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=freq, wait_dur=0.0, robust=False,
                    nuc='ple_A2', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=_I_['readout_dur'])
            elif _I_['readout'] == 'A1':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=freq, wait_dur=0.0, robust=False,
                    nuc='ple_A1', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=_I_['readout_dur'])
            mcas.asc(length_mus=0.5, name='waitAfterRead')

        self.queue._gated_counter.set_n_values(mcas, self.number_of_simultaneous_measurements)

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

    nuclear.parameters = OrderedDict(
        (
            ('sweeps', range(50)),
            ('A2_power',[5]),
            ('omega', [1/0.512]), # for projective electron pi 
            ('init_state', ['m12']),
            ('init_time', [100]),
            ('readout_dur', E.round_length_mus_to_x_multiple_ps([0.512])),
            ('amp', [0.18]), 
            ('readout', ['A2']),
            ('mw_freq',[12.785]),
            ('tau_rabi',E.round_length_mus_full_sample(np.linspace(0.0, 3.0*3, 30))), 
            ('cnot_freq',[168.95, 178.45]),
        )
    )
    nuclear.number_of_simultaneous_measurements =  2#len(nuclear.parameters['tau_rabi'])

def run_fun(abort, **kwargs):
    print(1,' Nuclear started!!!')
    nuclear.queue = kwargs['queue']
    nuclear.queue._gated_counter.readout_duration = 7*1e6 # --> nvalues.
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print('run_fun started')
    nuclear.run(abort)