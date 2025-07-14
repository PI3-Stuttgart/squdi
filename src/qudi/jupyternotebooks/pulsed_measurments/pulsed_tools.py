# You can copy this entire code block into a single cell in your Jupyter Notebook.

import numpy as np
import matplotlib.pyplot as plt


def create_simple_sequence(pulse_sequence_steps, channel_mapping):
    """
    Processes a user-defined sequence and returns the low-level data and total period.
    This is ideal for creating a single, fixed sequence.

    Args:
        pulse_sequence_steps (list): A list of dictionaries defining the pulse sequence.
        channel_mapping (dict): A map of channel names to physical channel numbers.

    Returns:
        tuple: (low_level_sequence, total_period_us)
    """
    print("--- Creating simple sequence ---")
    total_period_us = sum(step['duration_us'] for step in pulse_sequence_steps)
    
    low_level_sequence = []
    for step in pulse_sequence_steps:
        duration_ns = int(step['duration_us'] * 1000)
        # Safely get channel list, defaulting to empty if not provided
        channel_names_on = step.get('channels_on', [])
        high_channels = [channel_mapping.get(name) for name in channel_names_on]
        
        if duration_ns > 0:
            low_level_sequence.append((duration_ns, high_channels, 0.0, 0.0))
            
    print(f"Total sequence duration: {total_period_us:.2f} µs")
    return low_level_sequence, total_period_us

def create_sweep_sequence(sweep_params, subsequence_generator, channel_mapping):
    """
    Generates one single, continuous sequence for a sweep experiment.

    Args:
        sweep_params (dict): A dictionary with 'start', 'end', and 'steps' for the sweep.
        subsequence_generator (function): A function that takes a sweep value
                                          and returns the pulse steps for one sub-sequence.
        channel_mapping (dict): A map of channel names to physical channel numbers.

    Returns:
        tuple: (full_low_level_sequence, total_duration_us)
    """
    print(f"--- Creating sweep sequence with {sweep_params['steps']} steps ---")
    sweep_values = np.linspace(sweep_params['start'], sweep_params['end'], sweep_params['steps'])
    
    full_sequence_data = []
    
    for value in sweep_values:
        # 1. Generate the sub-sequence for the current sweep value
        sub_sequence_steps = subsequence_generator(value)
        
        # 2. Convert the sub-sequence to low-level format and append it
        for step in sub_sequence_steps:
            duration_ns = int(step['duration_us'] * 1000)
            channel_names_on = step.get('channels_on', [])
            high_channels = [channel_mapping.get(name) for name in channel_names_on]
            
            if duration_ns > 0:
                full_sequence_data.append((duration_ns, high_channels, 0.0, 0.0))

    total_duration_ns = sum(p[0] for p in full_sequence_data)
    total_duration_us = total_duration_ns / 1000.0
    
    print(f"Total continuous sequence duration: {total_duration_us:.2f} µs")
    return full_sequence_data, total_duration_us


# =================================================================================
#  PLOTTING FUNCTION (Adapted to plot a portion of a long sequence)
# =================================================================================
def plot_sequence(low_level_sequence, channel_mapping, plot_duration_us=None, title='Pulse Sequence'):
    """
    Generates a plot for a low-level pulse sequence. Can plot a partial duration.
    """
    plot_data = low_level_sequence
    
    # If a plot duration is specified, truncate the data for plotting
    if plot_duration_us is not None:
        plot_duration_ns = plot_duration_us * 1000
        plot_data = []
        current_time_ns = 0
        for pulse in low_level_sequence:
            plot_data.append(pulse)
            current_time_ns += pulse[0]
            if current_time_ns >= plot_duration_ns:
                break
    
    print(f"--- Generating Plot: {title} ---")
    fig, ax = plt.subplots(figsize=(15, 6))
    channel_names = {v: k for k, v in channel_mapping.items()}
    # Plot all channels defined in the map
    active_channels = sorted(list(channel_mapping.values()))

    for chan_num in active_channels:
        x_coords, y_coords = [0], [0]
        current_time_ns = 0
        for duration_ns, high_channels, _, _ in plot_data:
            level = 1 if chan_num in high_channels else 0
            if y_coords[-1] != level:
                x_coords.append(current_time_ns)
                y_coords.append(level)
            current_time_ns += duration_ns
            x_coords.append(current_time_ns)
            y_coords.append(level)
        
        time_us = np.array(x_coords) / 1000.0
        waveform = np.array(y_coords) * 0.8 + (chan_num - 1)
        ax.plot(time_us, waveform, label=channel_names.get(chan_num, f'CH {chan_num}'))

    ax.set_title(title, fontsize=16)
    ax.set_xlabel('Time (µs)', fontsize=12)
    ax.set_ylabel('Digital Channel', fontsize=12)
    ax.set_yticks([ch - 1 for ch in active_channels])
    ax.set_yticklabels([channel_names.get(ch, f'CH {ch}') for ch in active_channels])
    ax.set_ylim(-0.5, 8)
    ax.grid(axis='y', linestyle=':')
    ax.legend()
    plt.show()

print("Helper functions are defined and ready to use.")