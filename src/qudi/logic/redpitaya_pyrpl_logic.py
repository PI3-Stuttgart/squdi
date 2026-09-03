import numpy as np
from PySide2 import QtCore
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.interface.redpitaya_interface import RedPitayaInterface
from qudi.logic.eom_bias_wrapper import calculate_pid_wrap_preview


class RedPitayaPyrplLogic(LogicBase, RedPitayaInterface):
    """Logic module for Red Pitaya control using PyRPL."""

    # Connectors to hardware
    _redpitaya_hardware = Connector(name='redpitaya_hardware', interface='RedPitayaInterface')

    # Signals
    sigDataAcquired = QtCore.Signal(object, object, object)
    sigScopeStateChanged = QtCore.Signal(dict)
    sigPidBiasWrapperStatus = QtCore.Signal(object)
    _sigStartPidBiasWrapper = QtCore.Signal(object)
    _sigStopPidBiasWrapper = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._redpitaya_hardware_instance = None
        self._pid_bias_wrapper_timer = None
        self._pid_bias_wrapper_enabled = False
        self._pid_bias_wrapper_busy = False
        self._pid_bias_wrapper_config = {}
        self._pid_bias_wrapper_status = {
            'enabled': False,
            'state': 'stopped',
            'wrap_count': 0,
        }

    def on_activate(self):
        self._redpitaya_hardware_instance = self._redpitaya_hardware()
        self._pid_bias_wrapper_enabled = False
        self._pid_bias_wrapper_busy = False
        self._pid_bias_wrapper_config = {}
        self._pid_bias_wrapper_status = {
            'enabled': False,
            'state': 'stopped',
            'wrap_count': 0,
        }
        self._pid_bias_wrapper_timer = QtCore.QTimer()
        self._pid_bias_wrapper_timer.setSingleShot(False)
        self._pid_bias_wrapper_timer.timeout.connect(
            self._pid_bias_wrapper_tick,
            QtCore.Qt.QueuedConnection,
        )
        self._sigStartPidBiasWrapper.connect(
            self._start_pid_bias_wrapper,
            QtCore.Qt.QueuedConnection,
        )
        self._sigStopPidBiasWrapper.connect(
            self._stop_pid_bias_wrapper,
            QtCore.Qt.QueuedConnection,
        )

    def on_deactivate(self):
        if self._pid_bias_wrapper_timer is not None:
            self._pid_bias_wrapper_timer.stop()
            try:
                self._pid_bias_wrapper_timer.timeout.disconnect(
                    self._pid_bias_wrapper_tick
                )
            except (RuntimeError, TypeError):
                pass
        try:
            self._sigStartPidBiasWrapper.disconnect(
                self._start_pid_bias_wrapper
            )
        except (RuntimeError, TypeError):
            pass
        try:
            self._sigStopPidBiasWrapper.disconnect(
                self._stop_pid_bias_wrapper
            )
        except (RuntimeError, TypeError):
            pass
        self._pid_bias_wrapper_enabled = False
        self._pid_bias_wrapper_busy = False
        self._pid_bias_wrapper_timer = None
        self._redpitaya_hardware_instance = None

    def setup_scope(self, input1=None, input2=None, trigger_source='ch1_positive_edge', 
                   trigger_level=0.0, trigger_hysteresis=0.01, trigger_delay=0,
                   decimation=64, average=False, **kwargs):
        """Configure the oscilloscope settings."""
        try:
            # Configure basic scope settings
            self._redpitaya_hardware().setup_scope(
                input1=input1, input2=input2, 
                trigger_source=trigger_source,
                trigger_level=trigger_level, 
                trigger_hysteresis=trigger_hysteresis,
                trigger_delay=trigger_delay, 
                decimation=decimation, 
                average=average
            )
            
            # Start rolling mode with 1 second buffer
            self._redpitaya_hardware().start_rolling_mode(1.0)
            
            # Emit updated scope state
            state = self.get_scope_status()
            self.sigScopeStateChanged.emit(state)
            
        except Exception as e:
            self.log.error(f"Error setting up scope: {e}")

    def get_scope_data(self, seconds):
        """Get data directly from hardware's get_last_seconds."""
        try:
            hw = self._redpitaya_hardware()
            if hw is None:
                return None, None, None
            
            return hw.get_last_seconds(float(seconds))
            
        except Exception as e:
            self.log.error(f"Error getting scope data: {e}")
            return None, None, None

    def get_voltage(self, channel):
        """Get current voltage on a channel.
        """
        if self._redpitaya_hardware_instance:
            return self._redpitaya_hardware_instance.get_voltage(channel)
        return 0.0

    def get_scope_status(self):
        """Get current scope status.
        """
        if self._redpitaya_hardware_instance:
            return self._redpitaya_hardware_instance.get_scope_status()
        return {}

    def get_histogram(self):
        """Get histogram data from hardware."""
        try:
            # Get 1 second of data from hardware
            return self._redpitaya_hardware().get_last_seconds(1.0)
        except Exception as e:
            self.log.error(f'Error getting histogram: {e}')
            return None, None, None

    def get_pid_integrator(self, pid_channel=0):
        """Read a PID integrator value without changing hardware state."""
        if self._redpitaya_hardware_instance is None:
            raise RuntimeError("Red Pitaya hardware is not active.")
        return self._redpitaya_hardware_instance.get_pid_integrator(pid_channel)

    def get_pid_wrap_preview(
        self,
        pid_channel=0,
        vpi=0.36,
        min_value=-0.6,
        max_value=0.6,
        margin=0.05,
    ):
        """Calculate a P-aware wrap target without writing."""
        if self._redpitaya_hardware_instance is None:
            raise RuntimeError("Red Pitaya hardware is not active.")

        snapshot = self._redpitaya_hardware_instance.get_pid_output_snapshot(
            pid_channel
        )
        return calculate_pid_wrap_preview(
            snapshot=snapshot,
            vpi=vpi,
            min_value=min_value,
            max_value=max_value,
            margin=margin,
        )

    def get_pid_output_snapshot(self, pid_channel=0):
        """Read PID output diagnostics without changing hardware state."""
        if self._redpitaya_hardware_instance is None:
            raise RuntimeError("Red Pitaya hardware is not active.")
        return self._redpitaya_hardware_instance.get_pid_output_snapshot(
            pid_channel
        )

    def apply_pid_wrap(
        self,
        pid_channel=0,
        vpi=0.36,
        min_value=-0.6,
        max_value=0.6,
        margin=0.05,
        confirm=False,
        allow_windup_recovery=False,
    ):
        """Apply one explicitly confirmed wrap; never runs automatically."""
        preview = self.get_pid_wrap_preview(
            pid_channel=pid_channel,
            vpi=vpi,
            min_value=min_value,
            max_value=max_value,
            margin=margin,
        )

        if not preview['should_wrap']:
            preview.update(
                applied=False,
                action_reason='no_wrap_action_available',
            )
            return preview

        preview.update(
            applied=False,
            candidate_target=preview['target_integrator'],
        )
        if not preview['manual_write_ready']:
            preview['action_reason'] = 'pid_safety_check_failed'
            return preview
        if confirm is not True:
            return preview
        if (
            preview['action_mode'] == 'windup_recovery'
            and allow_windup_recovery is not True
        ):
            preview['action_reason'] = 'windup_recovery_not_allowed'
            return preview

        result = self._redpitaya_hardware_instance.set_pid_output_target_checked(
            pid_channel=pid_channel,
            expected_integrator=preview['integrator_after'],
            expected_output=preview['output'],
            target_output=preview['target_output'],
        )
        preview.update(
            applied=True,
            action_reason='applied',
            write_result=result,
        )
        return preview

    def start_pid_bias_wrapper(
        self,
        pid_channel=0,
        vpi=0.36,
        min_value=-0.6,
        max_value=0.6,
        margin=0.05,
        interval_seconds=1.0,
        allow_windup_recovery=True,
    ):
        """Request periodic bias wrapping; no module starts it automatically."""
        config = {
            'pid_channel': int(pid_channel),
            'vpi': float(vpi),
            'min_value': float(min_value),
            'max_value': float(max_value),
            'margin': float(margin),
            'interval_seconds': float(interval_seconds),
            'allow_windup_recovery': bool(allow_windup_recovery),
        }
        numeric_values = (
            config['vpi'],
            config['min_value'],
            config['max_value'],
            config['margin'],
            config['interval_seconds'],
        )
        if not all(np.isfinite(value) for value in numeric_values):
            raise ValueError("Bias-wrapper settings must be finite numbers.")
        if config['pid_channel'] not in (0, 1, 2):
            raise ValueError("Invalid PID channel. Must be 0, 1, or 2.")
        if config['vpi'] <= 0:
            raise ValueError("Vpi must be greater than zero.")
        if config['min_value'] >= config['max_value']:
            raise ValueError("min_value must be smaller than max_value.")
        if config['margin'] < 0:
            raise ValueError("margin must not be negative.")
        if (
            config['min_value'] + config['margin']
            >= config['max_value'] - config['margin']
        ):
            raise ValueError("margin leaves no usable bias range.")
        if config['interval_seconds'] < 0.2:
            raise ValueError("interval_seconds must be at least 0.2 seconds.")
        self._sigStartPidBiasWrapper.emit(config)
        return {'requested': True, **config}

    def stop_pid_bias_wrapper(self):
        """Request stopping the periodic bias wrapper."""
        self._sigStopPidBiasWrapper.emit()
        return {'requested': True}

    @QtCore.Slot(object)
    def _start_pid_bias_wrapper(self, config):
        if self._pid_bias_wrapper_timer is None:
            return
        self._pid_bias_wrapper_config = dict(config)
        self._pid_bias_wrapper_enabled = True
        self._pid_bias_wrapper_status = {
            **self._pid_bias_wrapper_config,
            'enabled': True,
            'state': 'starting',
            'wrap_count': 0,
        }
        self._pid_bias_wrapper_timer.start(
            max(200, int(round(config['interval_seconds'] * 1000.0)))
        )
        self.sigPidBiasWrapperStatus.emit(dict(self._pid_bias_wrapper_status))
        self._pid_bias_wrapper_tick()

    @QtCore.Slot()
    def _stop_pid_bias_wrapper(self):
        if self._pid_bias_wrapper_timer is not None:
            self._pid_bias_wrapper_timer.stop()
        self._pid_bias_wrapper_enabled = False
        self._pid_bias_wrapper_status = {
            **self._pid_bias_wrapper_status,
            'enabled': False,
            'state': 'stopped',
        }
        self.sigPidBiasWrapperStatus.emit(dict(self._pid_bias_wrapper_status))

    @QtCore.Slot()
    def _pid_bias_wrapper_tick(self):
        if not self._pid_bias_wrapper_enabled or self._pid_bias_wrapper_busy:
            return
        self._pid_bias_wrapper_busy = True
        try:
            config = self._pid_bias_wrapper_config
            preview = self.get_pid_wrap_preview(
                pid_channel=config['pid_channel'],
                vpi=config['vpi'],
                min_value=config['min_value'],
                max_value=config['max_value'],
                margin=config['margin'],
            )
            status = {
                **preview,
                **config,
                'enabled': True,
                'state': 'monitoring',
                'wrap_count': self._pid_bias_wrapper_status.get(
                    'wrap_count', 0
                ),
            }
            if preview['should_wrap']:
                if not preview['manual_write_ready']:
                    status.update(
                        enabled=False,
                        state='blocked',
                        error=preview['action_reason'],
                    )
                    self._pid_bias_wrapper_enabled = False
                    self._pid_bias_wrapper_timer.stop()
                elif (
                    preview['action_mode'] == 'windup_recovery'
                    and not config['allow_windup_recovery']
                ):
                    status.update(
                        enabled=False,
                        state='blocked',
                        error='windup_recovery_not_allowed',
                    )
                    self._pid_bias_wrapper_enabled = False
                    self._pid_bias_wrapper_timer.stop()
                else:
                    result = self.apply_pid_wrap(
                        pid_channel=config['pid_channel'],
                        vpi=config['vpi'],
                        min_value=config['min_value'],
                        max_value=config['max_value'],
                        margin=config['margin'],
                        confirm=True,
                        allow_windup_recovery=(
                            config['allow_windup_recovery']
                        ),
                    )
                    if not result['applied']:
                        if (
                            result.get('action_reason')
                            == 'no_wrap_action_available'
                        ):
                            # Normal near a threshold: the live output can
                            # move back into the safe range between preview
                            # and the guarded write check.
                            status.update(
                                result,
                                enabled=True,
                                state='monitoring',
                            )
                        else:
                            raise RuntimeError(
                                "Guarded PID wrap was requested but not applied."
                            )
                    else:
                        status.update(
                            result,
                            enabled=True,
                            state='wrapped',
                            wrap_count=status['wrap_count'] + 1,
                        )
            self._pid_bias_wrapper_status = status
            self.sigPidBiasWrapperStatus.emit(dict(status))
        except Exception as error:
            self._pid_bias_wrapper_enabled = False
            if self._pid_bias_wrapper_timer is not None:
                self._pid_bias_wrapper_timer.stop()
            self._pid_bias_wrapper_status = {
                **self._pid_bias_wrapper_status,
                'enabled': False,
                'state': 'error',
                'error': str(error),
            }
            self.log.error(f"PID bias wrapper stopped: {error}")
            self.sigPidBiasWrapperStatus.emit(
                dict(self._pid_bias_wrapper_status)
            )
        finally:
            self._pid_bias_wrapper_busy = False

    def get_pid_bias_wrapper_status(self):
        """Return the most recently published wrapper status."""
        return dict(self._pid_bias_wrapper_status)

    def get_pyrpl(self):
        """Get the underlying Pyrpl instance."""
        if self._redpitaya_hardware_instance is not None:
            return self._redpitaya_hardware_instance.get_pyrpl()
        return None

