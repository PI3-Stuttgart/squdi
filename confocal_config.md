#  Example Qudi configuration file.

global:
    # list of modules to load when starting
    startup: []

    # Module server configuration for accessing qudi GUI/logic/hardware modules from remote clients
    remote_modules_server:
        address: 'localhost'
        port: 12345

    # Server port for serving the active qudi module namespace locally (localhost).
    # Used by e.g. the Qudi jupyter kernel.
    namespace_server_port: 18861

    # If this flag is set (True), all arguments passed to qudi module APIs from remote
    # (jupyter notebook, qudi console, remote modules) will be wrapped and passed "per value"
    # (serialized and de-serialized). This is avoiding a lot of inconveniences with using numpy in
    # remote clients.
    # If you do not want to use this workaround and know what you are doing, you can disable this
    # feature by setting this flag to False.
    force_remote_calls_by_value: True

    # Qss stylesheet for controlling the appearance of the GUIs.
    # Absolute path or relative to qudi.artwork.styles
    stylesheet: 'qdark.qss'

    # Default root directory for measurement data storage. All eventual data sub-directories should
    # be contained within this directory. This is not enforced, just convention.
    # The fallback directory is <user home>/qudi/Data/
    # default_data_dir: C:\Users\neverhorst\qudi\Data

    # Save data to daily data sub-directories by default
    daily_data_dirs: True

gui:
    scanner_gui:
        module.Class: 'scanning.scannergui.ScannerGui'
        options:
            image_axes_padding: 0.02
            default_position_unit_prefix: null  # optional, use unit prefix characters, e.g. 'u' or 'n'
            optimizer_plot_dimensions: [2,1]
        connect:
            scanning_logic: scanning_probe_logic
            data_logic: scanning_data_logic
            optimize_logic: scanning_optimize_logic
    
    time_series_gui:
        module.Class: 'time_series.time_series_gui.TimeSeriesGui'
        options:
            use_antialias: True  # optional, set to False if you encounter performance issues
        connect:
            _time_series_logic_con: time_series_reader_logic

    spectrometer:
        module.Class: 'spectrometer.spectrometer_gui.SpectrometerGui'
        connect:
            spectrometer_logic: 'spectrometerlogic'
        
    timetagger:
        module.Class: 'timetagger.timetagger.TTGui'
        connect:
            timetaggerlogic: 'timetaggerlogic'
    
    odmr_gui:
        module.Class: 'odmr.odmrgui.OdmrGui'
        connect:
            odmr_logic: 'odmr_logic'
    
    dl_pro_gui:
        module.Class: 'laser.laser_gui.LaserGui'
        connect:
            laser_logic: 'dl_pro_logic'
    ple_gui:
        module.Class: 'ple.ple_gui.PLEScanGui'
        connect:
            scannerlogic: laser_scanner_logic
            # microwave: odmr_logic
            #repump: ple_repump_interfuse_logic
    pulsed_gui:
        module.Class: 'pulsed.pulsed_maingui.PulsedMeasurementGui'
        connect:
            pulsedmasterlogic: 'pulsed_master_logic'
            
logic:
    laser_scanner_logic:
        module.Class: 'ple.ple_scanner_logic.PLEScannerLogic'
        options:
            scan_axis: 'a'
            max_history_length: 10
            max_scan_update_interval: 2
            position_update_interval: 1
            channel: 'APD1'
        connect:
            scanner: ni_laser_scanner

    #ple_repump_interfuse_logic:
    #    module.Class: 'ple.repump_interfuse.RepumpInterfuseLogic'
    #    options:
    #        resonant_laser:  'd_ch1'
    #        repump_laser: 'd_ch2'
    #    connect:
    #        pulsed: pulsed_master_logic

    scanning_probe_logic:
        module.Class: 'scanning_probe_logic.ScanningProbeLogic'
        options:
            max_history_length: 10
            max_scan_update_interval: 2
            position_update_interval: 1
        connect:
            scanner: ni_scanner

    scanning_data_logic:
        module.Class: 'scanning_data_logic.ScanningDataLogic'
        options:
            max_history_length: 10
        connect:
            scan_logic: scanning_probe_logic

    scanning_optimize_logic:
        module.Class: 'scanning_optimize_logic.ScanningOptimizeLogic'
        connect:
            scan_logic: scanning_probe_logic

    time_series_reader_logic:
        module.Class: 'time_series_reader_logic.TimeSeriesReaderLogic'
        options:
            max_frame_rate: 10  # optional (10Hz by default)
            calc_digital_freq: True  # optional (True by default)
            active_channels: ['pfi8','pfi3']
        connect:
            streamer: ni_instreamer

    spectrometerlogic:
        module.Class: 'spectrometer_logic.SpectrometerLogic'
        connect:
            spectrometer: 'oceanoptics'
          
    timetaggerlogic:
        module.Class: 'timetagger_logic.TimeTaggerLogic'
        connect:
            timetagger: 'tagger'
    
    odmr_logic:
        module.Class: 'odmr_logic.OdmrLogic'
        connect:
            microwave: 'mw_source_smiq'
            data_scanner: 'ni_finite_sampling_input'

    

    dl_pro_logic:
        module.Class: 'laser_logic.LaserLogic'
        connect:
            laser: "dl_pro"

    pulsed_master_logic:
        module.Class: 'pulsed.pulsed_master_logic.PulsedMasterLogic'
        connect:
            pulsedmeasurementlogic: 'pulsed_measurement_logic'
            sequencegeneratorlogic: 'sequence_generator_logic'

    sequence_generator_logic:
        module.Class: 'pulsed.sequence_generator_logic.SequenceGeneratorLogic'
        #overhead_bytes: 0
        #additional_predefined_methods_path: null
        #additional_sampling_functions_path: null
        #assets_storage_path:
        connect:
            pulsegenerator: "pulsestreamer"

    pulsed_measurement_logic:
        module.Class: 'pulsed.pulsed_measurement_logic.PulsedMeasurementLogic'
        options:
            raw_data_save_type: 'text'
            #additional_extraction_path:
            #additional_analysis_path:
        connect:
            fastcounter: "fastcounter_timetagger"
            #microwave: 'microwave_dummy'
            pulsegenerator: "pulsestreamer"

    
hardware:

    fastcounter_timetagger:
        module.Class: 'swabian_instruments.timetagger_fast_counter.TimeTaggerFastCounter'
        options:
            timetagger_channel_apd_0: 1
            timetagger_channel_apd_1: 2
            timetagger_channel_detect: 3
            timetagger_channel_sequence: 8
            timetagger_sum_channels: 7
        connect:
            timetagger: 'tagger'
    
    tagger:
        module.Class: 'swabian_instruments.timetagger_api.TT'
        options:
            hist:
                channels: [1,2]
                trigger_channel: 5

            corr:
                channel_start: 1
                channel_stop: 2
            
            counter:
                channels: [1,2]

            combiner:
                channels: [1,2]

    ni_scanner:
        module.Class: 'interfuse.ni_scanning_probe_interfuse.NiScanningProbeInterfuse'
        connect:
            scan_hardware: 'ni_io'
            analog_output: 'ni_ao'
        options:
            ni_channel_mapping:
                z: 'ao2'
                x: 'ao1'
                y: 'ao0'
                APD1: 'PFI8'
                APD2: 'PFI3'
                #AI0: 'ai0'
                #APD3: 'PFI10'
            position_ranges: # in m
                z: [-7.5e-6, 7.5e-6]
                x: [-20e-6, 20e-6]
                y: [-20e-6, 20e-6]
            frequency_ranges:
                z: [1, 500]
                x: [1, 500]
                y: [1, 500]
            resolution_ranges:
                z: [1, 1000]
                x: [1, 1000]
                y: [1, 1000]
            input_channel_units:
                APD1: 'c/s'
                APD2: 'c/s'
                #AI0: 'V'
                #APD2: 'c/s'
                #APD3: 'c/s'
            backwards_line_resolution: 50 # optional
            maximum_move_velocity: 400e-6 #m/s

    ni_laser_scanner:
        module.Class: 'interfuse.ni_scanning_probe_interfuse.NiScanningProbeInterfuse'
        connect:
            scan_hardware: 'ni_io'
            analog_output: 'ni_ao'
        options:
            ni_channel_mapping:
                a: 'ao3'
                APD1: 'PFI8'
                APD2: 'PFI3'
                #AI0: 'ai0'
                #APD3: 'PFI10'
            position_ranges: # in m
                a: [-4, 4]
            frequency_ranges:
                a: [1, 500]
            resolution_ranges:
                a: [20, 1000]
            input_channel_units:
                APD1: 'c/s'
                APD2: 'c/s'
                #AI0: 'V'
                #APD2: 'c/s'
                #APD3: 'c/s'
            backwards_line_resolution: 50 # optional
            maximum_move_velocity: 400 #m/s

    ni_io:
        module.Class: 'ni_x_series.ni_x_series_finite_sampling_io.NIXSeriesFiniteSamplingIO'
        options:
            device_name: 'Dev1'
            input_channel_units:  # optional
                PFI8: 'c/s'
                PFI3: 'c/s'
                #PFI10: 'c/s'
                #ai0: 'V'
                #ai1: 'V'
            output_channel_units:
                'ao0': 'V'
                'ao1': 'V'
                'ao2': 'V'
                'ao3': 'V'
            #adc_voltage_ranges:
                #ai0: [-10, 10]  # optional
                #ai1: [-10, 10]  # optional
            output_voltage_ranges:
                ao0: [0, 4]
                ao1: [0, 4]
                ao2: [0, 4]
                ao3: [-4, 4]
    
            
            #TODO output range, also limits need to be included in constraints
            frame_size_limits: [1, 1e9]  # optional #TODO actual HW constraint?
            output_mode: 'JUMP_LIST' #'JUMP_LIST' # optional, must be name of SamplingOutputMode
            read_write_timeout: 10  # optional
            #sample_clock_output: '/Dev1/PFI11' # optional

    ni_ao:
        module.Class: 'ni_x_series.ni_x_series_analog_output.NIXSeriesAnalogOutput'
        options:
            device_name: 'Dev1'

            setpoint_channels:
                ao0:
                    unit: 'V'
                    limits: [0, 4]
                    keep_value: True
                ao1:
                    unit: 'V'
                    limits: [0, 4]
                    keep_value: True
                ao2:
                    unit: 'V'
                    limits: [0, 4]
                    keep_value: True
                ao3:
                    unit: 'V'
                    limits: [-4, 4]
                    keep_value: True


    
    # optional, for slow counter / timer series reader
    ni_instreamer:
        module.Class: 'ni_x_series.ni_x_series_in_streamer.NIXSeriesInStreamer'
        options:
            device_name: 'Dev1'
            digital_sources:  # optional
                - 'pfi8'
                - 'pfi3'
            # analog_sources:  # optional
            #   - 'ai0'
            #   - 'ai1'
            # external_sample_clock_source: 'PFI0'  # optional
            # external_sample_clock_frequency: 1000  # optional
            # adc_voltage_range: [-10, 10]  # optional
            max_channel_samples_buffer: 10000000  # optional
            read_write_timeout: 10  # optional

    oceanoptics:
        module.Class: 'spectrometer.oceanoptics_spectrometer.OceanOptics'

    myspectrometer:
        module.Class: 'dummy.spectrometer_dummy.SpectrometerDummy'
    
    microwave_dummy:
        module.Class: 'dummy.microwave_dummy.MicrowaveDummy'

    mw_source_smiq:
        module.Class: 'microwave.mw_source_smiq.MicrowaveSmiq'
        options:
            visa_address: 'GPIB0::29::INSTR'
            comm_timeout: 10000  # in milliseconds

    finite_sampling_input_dummy:
        module.Class: 'dummy.finite_sampling_input_dummy.FiniteSamplingInputDummy'
        options:
            simulation_mode: 'ODMR'
            sample_rate_limits: [1, 1e6]
            frame_size_limits: [1, 1e9]
            channel_units:
                'APD counts': 'c/s'
                'Photodiode': 'V'
    
    ni_finite_sampling_input:
        module.Class: 'ni_x_series.ni_x_series_finite_sampling_input.NIXSeriesFiniteSamplingInput'
        options:
            device_name: 'Dev1'
            digital_channel_units:  # optional
                'pfi8': 'cnts'
                'pfi3': 'cnts'
            max_channel_samples_buffer: 10000000  # optional, default 10000000
            read_write_timeout: 10  # optional, default 10
            sample_clock_output: '/Dev1/PFI14'  # optional
    
    dl_pro:
        module.Class: 'laser.toptica_dl_pro.DlProLaser'
        options:
            tcp_address: '169.254.128.41'
            current_range: [0, 90]
        
    high_finesse_wavemeter:
        module.Class: 'high_finesse_wavemeter.HighFinesseWavemeter'
        options:
            measurement_timing: 10.0 # in seconds

    pulsestreamer:
        module.Class: 'swabian_instruments.pulse_streamer.PulseStreamer'
        options:
            pulsestreamer_ip: '129.69.46.189'
            #pulsed_file_dir: 'C:\\Software\\pulsed_files'
            laser_channel: 0
            uw_x_channel: 1
            use_external_clock: False
            external_clock_option: 0