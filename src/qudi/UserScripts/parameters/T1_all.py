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
    RF_init12p = 0
    RF_init12m = 0
    ## MW drive
    if 'p' in state:
            mw_init32L1 = 0.3
            mw_init32L2 = 0.3
    elif 'm' in state:
            mw_init32R1 = 0.3
            mw_init32R2 = 0.3
    pd2g1 = {
        'type':'sine',
        'phases':[0],
        'amplitudes':[
                    mw_init32L1,
                    mw_init32L2,
                    mw_init32R1,
                    mw_init32R2],                    
        #'frequencies':[30.5,38.5],
        'frequencies':freqs
    }
    
    return pd2g1


def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name = None):
        sequence_name = 'Electron_rabi_test' if sequence_name is None else sequence_name
        mcas = MultiChSeq(name=sequence_name, ch_dict={'2g': [1,2], 'ps': [1]}) #Only use one channel - it is faster...
        for idx, _I_ in current_iterator_df.iterrows():
            mcas.start_new_segment(name='init')
            mcas.asc(length_mus=5.0, repump=True, name='Repump')
            mcas.asc(length_mus=2.0)  # Starting... histogram 0
        
            print('Initialising to', _I_['init_state'])
            state = _I_['init_state']
            mcas.asc(
                A1='32' in state,
                A2='12' in state,
                length_mus=_I_['init_time'],
                name='resonant_init',
                pd2g1=init_state_drive(state, [35.65, 37.9, 175.1, 177.25])
            )

            mcas.start_new_segment(name='T1 time')
            mcas.asc(name = 'T1', length_mus = _I_['T1'])

            # mcas.start_new_segment(name='Rabi')
            # freqs = {'L1': 35.65, 'L2': 37.9, 'C1': 107.9, 'C2': 98.4, 'R1': 168.4, 'R2': 177.78}[_I_['trans']]
            # amp_omega = self.queue.tt.rp('e_rabi_ou350deg-90-'+_I_['trans'][0], omega=_I_['amp_omega']).amp
            # sna.electron_rabi(
            #     mcas,
            #     new_segment=False,
            #     length_mus= _I_['tau'],
            #     amplitudes=[amp_omega],
            #     frequencies=[freqs],
            #     mixer_deg=[-90]
            # )

            # if _I_['trans'].startswith('C'):
            #     pi_durR = self.queue.tt.rp('e_rabi_ou350deg-90-R2', omega=1.5).pi
            #     ampR1 = self.queue.tt.rp('e_rabi_ou350deg-90-R1', omega=1.5).amp
            #     ampR2 = self.queue.tt.rp('e_rabi_ou350deg-90-R2', omega=1.5).amp

            #     sna.electron_rabi(
            #         mcas,
            #         new_segment=False,
            #         length_mus= pi_durR,
            #         amplitudes=[ampR1, ampR2],
            #         frequencies=[168.4,177.78],
            #         mixer_deg=[-90,-90]
            #     )

            #mcas.asc(length_mus=0.5, name='sequence wait 1')
            if _I_['readout'] == 'A2':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=[30.0], wait_dur=0.0, robust=False,
                    nuc='ple_A2', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=_I_['t_read'])
            elif _I_['readout'] == 'A1':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=[30.0], wait_dur=0.0, robust=False,
                    nuc='ple_A1', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=_I_['t_read'])
            mcas.asc(length_mus=0.5, name='sequence wait 2')

        self.queue._gated_counter.set_n_values(mcas, self.number_of_simultaneous_measurements) #how to get here the queue? readout duration/sequence length.

        return mcas
    return ret_mcas

def settings(pdc={}):
    ana_seq=[
        ['result', '>', 0, 1, 0, 1],
    ]
        
    sch.settings(
        nuclear=nuclear,
        ret_mcas=ret_ret_mcas(pdc),
        analyze_sequence=ana_seq,
        pdc=pdc,
        meas_code=meas_code
    )

    nuclear.x_axis_title = 'Index'
    nuclear.analyze_type = 'average' #experimental feature for the fast 
    nuclear.save_smartly = True
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
    nuclear.odmr_refocus_interval= 1200
    #rabi refocus ?
    nuclear.queue._gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue._gated_counter.trace.average_results = False

    nuclear.parameters = OrderedDict( # WHAT DOES ALL THIS MEAN ??? WHICH UNITS ??
        (
            ('sweeps', range(50)),
            ('t_read',[0.3]),
            ('A2_power',[5]),
            ('init_time', [70]),
            ('init_state', ['p32','p12', 'm12', 'm32']),
            #('amp_omega', [2]), 
            #('trans',['L1','L2']),
            ('readout', ['A2','A1']),
            #('tau', E.round_length_mus_full_sample(np.linspace(0,1,9))),
            #('T1', E.round_length_mus_full_sample_ps(np.unique(np.logspace(0,3,20, dtype = int)))),
            ('T1', E.round_length_mus_full_sample_ps(np.unique(np.logspace(0,5,20, dtype = int)))),
        )
    )
    nuclear.number_of_simultaneous_measurements = len(nuclear.parameters['T1'])

def run_fun(abort, **kwargs):
    print(1,' Nuclear started!!!')
    nuclear.queue = kwargs['queue']
    nuclear.queue._gated_counter.readout_duration = 150*1e6 # --> nvalues.
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print('run_fun started')
    nuclear.run(abort)
    
