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
        sequence_name = 'Nuclear_rabi' if sequence_name is None else sequence_name
        #print(self, current_iterator_df)
        
        mcas = MultiChSeq(name=sequence_name, ch_dict={'2g': [1, 2], 'ps': [1]})
        mcas.start_new_segment('start_sequence')
        mcas.asc(length_mus=5.0, repump=True, name='Repump')
        mcas.asc(length_mus=10.0)
        for idx, _I_ in current_iterator_df.iterrows():
            mcas.start_new_segment('FID')
            
            # Amplitudes for C(n)NOT(e)
            pi_dur = self.queue.tt.rp('e_rabi_ou350deg-90-L2', omega=_I_['omega']).pi
            L2amp = self.queue.tt.rp('e_rabi_ou350deg-90-L2', omega=_I_['omega']).amp
            R2amp  = self.queue.tt.rp('e_rabi_ou350deg-90-R2', omega=_I_['omega']).amp

            # Init in -32m
            mcas.asc(
                A1=_I_['init']=='A1',
                A2 =_I_['init']=='A2', 
                length_mus=_I_['init_time'], 
                name='resonant_init',
                pd2g1 = {
                    'type':'sine',
                    'phases':[0],
                    'amplitudes':[0.02],
                    'frequencies':[177.8,168.4]
                })
            
            mcas.asc(length_mus=1.0, name='wait after init')

            # nuc pi/2
            sna.electron_rabi(
                mcas,
                new_segment=False,
                length_mus= 0.48*0.5,
                amplitudes=[0.18],
                frequencies=[_I_['mw_freq']],
                mixer_deg=[-90]
            )

            # evolution time
            mcas.asc(length_mus=_I_['tau_rabi'], name='fid')

            # nuc pi/2
            sna.electron_rabi(
                mcas,
                new_segment=False,
                length_mus= 0.48*0.5,
                amplitudes=[0.18],
                frequencies=[_I_['mw_freq']],
                phases = [_I_['readout_phase']],
                mixer_deg=[-90]
            )

            mcas.asc(length_mus=0.01, name='wait after FID')

            # CNOT to -12p
            sna.electron_rabi(
                mcas,
                new_segment=False,
                length_mus= pi_dur,
                amplitudes=[L2amp],
                frequencies=[_I_['cnot_freq']],
                mixer_deg=[-90]
            )
            
            mcas.asc(length_mus=0.1, name='wait after CNOT')

            # [38.45, 177.8] correspond to CNOT between 1/2 and 3/2 subspaces conditional on nuclear spin.
            sna.ssr(mcas = mcas, queue=self.queue, frequencies=[[38.45, 177.8]], wait_dur=0.0, robust=False, 
                    nuc='29Si8_A2', mixer_deg=-90, eom_ampl=0.0, 
                    step_idx=0, laser_dur=_I_['laser_dur'], length_mus_mw = pi_dur, amplitudes=[L2amp,R2amp], repetitions = _I_['n_ssr']
                    )
            mcas.asc(length_mus=0.5, name='wait final')

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

    nuclear.ple_refocus_interval = 300
    nuclear.confocal_refocus_interval = 300  # seconds
    nuclear.odmr_refocus_interval= 600

    #rabi refocus ?

    nuclear.queue._gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue._gated_counter.trace.average_results = False

    # parameters defines the iteration with the various different measurement settings (frequencies, durations, readout lasers,...)
    nuclear.parameters = OrderedDict(
        (
            ('sweeps', range(20)),
            ('A2_power',[3]),
            ('omega', [1.5]),
            ('init', ['A1']),
            ('init_time', [100]),
            ('readout', ['A2']),
            ('cnot_freq',[38.45]),
            ('mw_freq',[14.25]),
            ('laser_dur',[6.]),
            ('n_ssr', [20,40,60,80,100]),
            #('n_ssr', [15,50,100]),
            ('tau_rabi',E.round_length_mus_full_sample(np.linspace(0.0, 15.0, 31))), 
            ('readout_phase',[0,180])
        )
    )
    nuclear.number_of_simultaneous_measurements =  2

def run_fun(abort, **kwargs):
    print(1,' Nuclear started!!!')
    nuclear.queue = kwargs['queue']
    nuclear.queue._gated_counter.readout_duration = 5*1e6
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print('run_fun started')
    nuclear.run(abort)
    