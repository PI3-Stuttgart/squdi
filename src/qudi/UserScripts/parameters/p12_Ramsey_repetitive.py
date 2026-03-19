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
        
        mcas = MultiChSeq(name=sequence_name, ch_dict={'2g': [1, 2], 'ps': [1]})
        mcas.start_new_segment('start_sequence')
        mcas.asc(length_mus=5.0, repump=True, name='Repump')
        mcas.asc(length_mus=1.0)  # Starting... histogram 0
        for idx, _I_ in current_iterator_df.iterrows():
            
            pi_dur = self.queue.tt.rp('e_rabi_ou350deg-90-L2', omega=_I_['omega']).pi
            
            R1amp = self.queue.tt.rp('e_rabi_ou350deg-90-R1', omega=_I_['omega']).amp
            R2amp = self.queue.tt.rp('e_rabi_ou350deg-90-R2', omega=_I_['omega']).amp
            L2amp = self.queue.tt.rp('e_rabi_ou350deg-90-L2', omega=_I_['omega']).amp
            C2amp = self.queue.tt.rp('e_rabi_ou350deg-90-C2', period = 1.0).amp
            mcas.asc(
                A1 = _I_['init']=='A1',
                A2 = _I_['init']=='A2', 
                length_mus=_I_['init_time'], 
                name='resonant_init',
                pd2g1 = {
                    'type':'sine',
                    'phases':[0],
                    'amplitudes':[_I_['mw_init']],#0.02
                    'frequencies':[177.7,168.4]
                })  # Init system with A2 laser - into -1/2.
            
            mcas.asc(length_mus=10.0, name='sequence wait 1')
            
            ## swap to plus - a pi pulse for Center transitions
            mcas.asc(length_mus=0.1)
            
            sna.electron_rabi(
                mcas,
                new_segment=False,
                length_mus= 0.5,
                amplitudes=[C2amp],
                frequencies=[107.8], #mfl --> gives the frequency , (12-12m, 29Si8+)
                mixer_deg=[-90]) # Rabi 1/2-1/2 pi pulse. 


            mcas.asc(length_mus=0.1)

            sna.electron_rabi(
                mcas,
                new_segment=False,
                length_mus=_I_['mw_duration'],
                amplitudes=[_I_['RF_amp']],
                frequencies=[_I_['RF_freq']],
                mixer_deg=[-90]
            )
            #/2 to -1/2 ?? 
            if _I_['cnot_freq'] ==168.4:
                sna.electron_rabi(
                    mcas,
                    new_segment=False,
                    length_mus= 0.25,
                    #length_mus= _I_['mw_dur_R1'],
                    amplitudes=[R1amp],
                    frequencies=[_I_['cnot_freq']],
                    mixer_deg=[-90]
                ) # ODMR 
            else:
                sna.electron_rabi(
                    mcas,
                    new_segment=False,
                    length_mus= 0.5,
                    #length_mus= _I_['mw_dur_R1'],
                    amplitudes=[R2amp],
                    frequencies=[_I_['cnot_freq']],
                    mixer_deg=[-90]
                ) # ODMR 


            mcas.asc(length_mus=0.1, name='wait after CNOT')

            # [38.45, 177.8] correspond to CNOT between 1/2 and 3/2 subspaces conditional on nuclear spin.
            sna.ssr(mcas = mcas, queue=self.queue, frequencies=[[38.45, 177.8]], wait_dur=0.0, robust=False, 
                    nuc='29Si8_A2', mixer_deg=-90, eom_ampl=0.0, 
                    step_idx=0, laser_dur=_I_['laser_dur'], length_mus_mw = pi_dur, amplitudes=[L2amp,R2amp], repetitions = _I_['n_ssr']
                    )
            mcas.asc(length_mus=0.5, name='wait final')

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
            ('omega', [1.0]),
            ('readout', ['A2']),
            ('sweeps', range(4)),
            ('RF_amp',[0.2]),
            ('MW -3to-1',[False]),
            ('RF_freq',[3.263]),
            ('laser_dur',[6.]),
            ('n_ssr', [20,40,60,80,100]),
            ('mw_duration',E.round_length_mus_full_sample(np.linspace(0.0, 10, 26))),
            ('init_time', [100]),
            ('mw_init',[0.02]),
            ('A2_power',[3]),
            ('init', ['A2']),
            ('cnot_freq',[168.4,177.8]),#np.linspace(90,130,40)), 
        )
    )
    nuclear.number_of_simultaneous_measurements =  1#*len(nuclear.parameters['mw_duration'])

def run_fun(abort, **kwargs):
    print(1,' Nuclear started!!!')
    nuclear.queue = kwargs['queue']
    nuclear.queue._gated_counter.readout_duration = 3*1e6 # --> nvalues.
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print('run_fun started')
    nuclear.run(abort)