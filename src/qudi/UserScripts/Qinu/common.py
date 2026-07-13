# coding=utf-8
from __future__ import absolute_import, division, print_function

import os

import qudi.UserScripts.helpers.sequence_creation_helpers as sch


def create_experiment(script_path):
    """Create the NuclearOPs object and collect script metadata."""
    seq_name = os.path.basename(script_path).split(".")[0]
    nuclear = sch.create_nuclear(script_path)
    with open(os.path.abspath(script_path), "r") as script_file:
        meas_code = script_file.read()
    return nuclear, meas_code, seq_name


def ana_step(
    step_type,
    operator,
    threshold,
    nlp_per_point=1,
    threshold_delta=0,
    number_of_results=1,
    apd=None,
):
    """Build one analyze_sequence step.

    The first six values are the legacy Analysis.Trace format. ``apd`` is the
    optional seventh field used by the multi-APD gated counter path.
    """
    step = [
        step_type,
        operator,
        threshold,
        nlp_per_point,
        threshold_delta,
        number_of_results,
    ]
    if apd is not None:
        step.append(apd)
    return step


def init(operator, threshold, nlp_per_point=1, threshold_delta=0, number_of_results=1, apd=None):
    return ana_step(
        "init",
        operator,
        threshold,
        nlp_per_point=nlp_per_point,
        threshold_delta=threshold_delta,
        number_of_results=number_of_results,
        apd=apd,
    )


def result(operator, threshold, nlp_per_point=1, threshold_delta=0, number_of_results=1, apd=None):
    return ana_step(
        "result",
        operator,
        threshold,
        nlp_per_point=nlp_per_point,
        threshold_delta=threshold_delta,
        number_of_results=number_of_results,
        apd=apd,
    )


def configure_experiment(
    nuclear,
    ret_mcas,
    analyze_sequence,
    meas_code,
    pdc=None,
    analyze_type="average",
    save_smartly=False,
    no_trace=False,
    ple_refocus=False,
    lock_laser_to_wavemeter=False,
    ple_refocus_interval=2 * 60,
    confocal_refocus_red=False,
    confocal_refocus_green=False,
    confocal_refocus_interval=10 * 60,
    consecutive_valid_result_numbers=None,
    average_results=False,
):
    """Apply the Qinu defaults shared by most single-experiment scripts."""
    pdc = {} if pdc is None else pdc
    consecutive_valid_result_numbers = (
        [0] if consecutive_valid_result_numbers is None else consecutive_valid_result_numbers
    )

    sch.settings(
        nuclear=nuclear,
        ret_mcas=ret_mcas,
        analyze_sequence=analyze_sequence,
        pdc=pdc,
        meas_code=meas_code,
    )

    nuclear.analyze_type = analyze_type
    nuclear.save_smartly = save_smartly
    nuclear.no_trace = no_trace

    nuclear.do_ple_refocus_A1 = ple_refocus
    nuclear.lock_laser_to_wavemeter = lock_laser_to_wavemeter
    nuclear.ple_refocus_interval = ple_refocus_interval

    nuclear.do_confocal_refocus_red = confocal_refocus_red
    nuclear.do_confocal_refocus_green = confocal_refocus_green
    nuclear.confocal_refocus_interval = confocal_refocus_interval

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = (
        consecutive_valid_result_numbers
    )
    nuclear.queue.gated_counter.trace.average_results = average_results


def set_counter_length(
    nuclear,
    repetitions,
    analyze_sequence,
    readouts_per_repetition=None,
    sm=1,
):
    """Set gated-counter n_values from the experiment dimensions."""
    if readouts_per_repetition is None:
        readouts_per_repetition = sum(step[3] for step in analyze_sequence)
    n_values = (
        nuclear.number_of_simultaneous_measurements
        * repetitions
        * readouts_per_repetition
    )
    nuclear.queue.gated_counter.set_n_values(mcas=None, sm=sm, n_values=n_values)
    return n_values


def run_nuclear_experiment(
    nuclear,
    abort,
    queue,
    settings,
    readout_duration=1e6,
    hashed=False,
    debug_mode=False,
):
    print(1, "Nuclear started!!!")
    nuclear.queue = queue
    nuclear.queue.gated_counter.readout_duration = readout_duration
    nuclear.hashed = hashed
    nuclear.debug_mode = debug_mode
    settings()
    print("run_fun started")
    nuclear.run(abort)
