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
            mw_init32R2 = 0.08
            mw_init32m = 0.4
        elif '-' in state:
            RF_init12m = 0.0
            mw_init32R1 = 0.08
            mw_init32m = 0.0
    elif 'm' in state:
        mw_init32R2 = 0.04
        mw_init32R1 = 0.04

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
        'frequencies': [177.78, 168.4, 30.5, 38.5, 3.4, 6.47]
    }

    return pd2g1

def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name = None):
        sequence_name = 'Electron_rabi_test' if sequence_name is None else sequence_name
        
        mcas = MultiChSeq(name=sequence_name, ch_dict={'2g': [1,2], 'ps': [1]})
        mcas.start_new_segment('start_sequence')
        
        for idx, _I_ in current_iterator_df.iterrows():
            
            ### Repump ###
            mcas.asc(length_mus=40.0, repump=True, name='Repump')
            mcas.asc(length_mus=1.0)

            ### Resonant Init ###
            state = _I_['init_state']
            mcas.asc(
                A1='32' in state,
                A2='12' in state,
                length_mus=_I_['init_time'],
                name='resonant_init',
                pd2g1=init_state_drive(state)
            )
            mcas.asc(length_mus=_I_['waitAfterInit'], name='waitAfterInit')
            
            ### Rabi Pulse ###
            freqs = {'L1': 30.4, 'L2': 38.4, 'C1': 98.3, 'C2': 107.95, 'R1': 168.24, 'R2': 177.72, 'L': [30.4, 38.4], 'C': [98.3, 107.95],'R': [168.24, 177.72]}[_I_['trans']]
            if _I_['trans'][-1] == '1' or _I_['trans'][-1] == '2':
                amp = self.queue.tt.rp('e_rabi_ou350deg-90-'+_I_['trans'], omega=_I_['amp_omega']).amp
                sna.electron_rabi(
                    mcas,
                    new_segment=False,
                    length_mus= _I_['tau'],
                    amplitudes=[amp],
                    frequencies=[freqs],
                    mixer_deg=[-90]
                )
                
            else:
                amp_omega1 = self.queue.tt.rp('e_rabi_ou350deg-90-'+_I_['trans']+'1', omega=_I_['amp_omega']).amp
                amp_omega2 = self.queue.tt.rp('e_rabi_ou350deg-90-'+_I_['trans']+'2', omega=_I_['amp_omega']).amp
            
                sna.electron_rabi(
                    mcas,
                    new_segment=False,
                    length_mus= _I_['tau'],
                    amplitudes=[amp_omega1, amp_omega2],
                    frequencies=freqs,
                    mixer_deg=[-90,90]
                )

            ### Project to p32 state ###
            if _I_['trans'].startswith('C'):
                pi_durR = self.queue.tt.rp('e_rabi_ou350deg-90-R2', omega=2).pi
                ampR1 = self.queue.tt.rp('e_rabi_ou350deg-90-R1', omega=2).amp
                ampR2 = self.queue.tt.rp('e_rabi_ou350deg-90-R2', omega=2).amp

                sna.electron_rabi(
                    mcas,
                    new_segment=False,
                    length_mus= pi_durR,
                    amplitudes=[ampR1, ampR2],
                    frequencies=[168.24,177.72],
                    mixer_deg=[-90,-90]
                )
            mcas.asc(length_mus=0.25, name='waitAfterInit')
            
            ### Readout ###
            freq = [30.0]
            if _I_['readout'] == 'A2':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=freq, wait_dur=0.0, robust=False,
                    nuc='ple_A2', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=_I_['t_read'])
            elif _I_['readout'] == 'A1':
                sna.ssr(mcas = mcas, queue=self.queue, frequencies=freq, wait_dur=0.0, robust=False,
                    nuc='ple_A1', mixer_deg=-90, eom_ampl=0.0, step_idx=0, laser_dur=_I_['t_read'])
            mcas.asc(length_mus=0.5, name='sequence wait 2')

        self.queue._gated_counter.set_n_values(mcas, self.number_of_simultaneous_measurements)

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
    nuclear.ple_refocus_interval = 1200
    nuclear.confocal_refocus_interval = 1200  # seconds
    nuclear.odmr_refocus_interval= 1200
    
    nuclear.queue._gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue._gated_counter.trace.average_results = False

    nuclear.parameters = OrderedDict(
        (
            ('sweeps', range(5)),
            ('A2_power',[5]),
            ('init_time', [10.0, 20.0, 50.0, 100.0, 150.0]),
            ('amp_omega', [2]), 
            ('t_read', [0.05]),
            ('waitAfterInit', [1]),
            ('init_state', ['m32-', 'm12+']),
            ('trans', ['L', 'C', 'R', 'L1','L2', 'R1','R2']),
            ('tau', E.round_length_mus_full_sample(np.linspace(0,1,17))),
            ('readout', ['A2','A1']),
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
    
