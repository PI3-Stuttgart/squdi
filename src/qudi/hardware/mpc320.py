"""Qudi hardware module for the Thorlabs MPC320 polarization controller."""

import os
import sys
import time

from qudi.core.configoption import ConfigOption
from qudi.core.module import Base


class MPC320(Base):
    """Control the three paddles of a Thorlabs MPC320 via Kinesis."""

    _kinesis_path = ConfigOption('kinesis_path', default=r'C:\Program Files\Thorlabs\Kinesis')
    _serial = ConfigOption('serial', default=None, missing='nothing')
    _polling_interval_ms = ConfigOption('polling_interval_ms', default=250)
    _move_timeout_s = ConfigOption('move_timeout_s', default=20.0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._device = None
        self._paddles = None
        self._paddle_map = None

    def on_activate(self):
        """Connect to Kinesis and enable the configured MPC320."""
        if not os.path.isdir(self._kinesis_path):
            raise FileNotFoundError(f'Thorlabs Kinesis directory not found: {self._kinesis_path}')
        if self._kinesis_path not in sys.path:
            sys.path.append(self._kinesis_path)
        os.environ['PATH'] = self._kinesis_path + os.pathsep + os.environ.get('PATH', '')

        import clr
        clr.AddReference('Thorlabs.MotionControl.DeviceManagerCLI')
        clr.AddReference('Thorlabs.MotionControl.PolarizerCLI')
        from System import Decimal
        from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI
        from Thorlabs.MotionControl.PolarizerCLI import Polarizer, PolarizerPaddles

        self._decimal = Decimal
        self._device_manager = DeviceManagerCLI
        self._device_manager.BuildDeviceList()
        devices = list(self._device_manager.GetDeviceList())
        if not devices:
            raise RuntimeError('No MPC320 found by Thorlabs Kinesis')
        serial = self._serial or devices[0]
        if serial not in devices:
            raise RuntimeError(f'Configured MPC320 serial {serial!r} was not found; available: {devices}')

        self._device = Polarizer.CreatePolarizer(serial)
        self._device.Connect(serial)
        self._device.WaitForSettingsInitialized(5000)
        self._device.StartPolling(int(self._polling_interval_ms))
        time.sleep(0.5)
        self._device.EnableDevice()
        time.sleep(0.5)
        self._paddle_map = {
            1: PolarizerPaddles.Paddle1,
            2: PolarizerPaddles.Paddle2,
            3: PolarizerPaddles.Paddle3,
        }
        self.log.info('Connected MPC320 serial %s', serial)

    def on_deactivate(self):
        """Stop polling and disconnect without leaving a Kinesis connection open."""
        if self._device is None:
            return
        try:
            self._device.StopPolling()
            self._device.Disconnect(True)
        finally:
            self._device = None
            self._paddle_map = None

    def _paddle(self, paddle):
        if paddle not in (1, 2, 3):
            raise ValueError('paddle must be 1, 2, or 3')
        return self._paddle_map[paddle]

    def _require_device(self):
        if self._device is None:
            raise RuntimeError('MPC320 is not active')

    def position(self, paddle):
        """Return one paddle position in degrees."""
        self._require_device()
        return float(str(self._device.Status(self._paddle(paddle)).Position).replace(',', '.'))

    def positions(self):
        """Return all paddle positions in degrees as ``[p1, p2, p3]``."""
        self._require_device()
        self._device.RequestPositions()
        return [self.position(paddle) for paddle in (1, 2, 3)]

    def is_moving(self, paddle):
        self._require_device()
        return bool(self._device.Status(self._paddle(paddle)).IsMoving)

    def wait(self, paddle, timeout=None):
        """Wait for one paddle, with a deadline to prevent a stuck motion."""
        timeout = self._move_timeout_s if timeout is None else float(timeout)
        deadline = time.monotonic() + timeout
        while self.is_moving(paddle):
            if time.monotonic() >= deadline:
                raise TimeoutError(f'MPC320 paddle {paddle} did not finish within {timeout:g} s')
            time.sleep(0.1)

    def move(self, paddle, angle, timeout=None):
        """Move one paddle to an absolute angle in the 0–160 degree range."""
        angle = float(angle)
        if not 0.0 <= angle <= 160.0:
            raise ValueError('MPC320 paddle angles must be between 0 and 160 degrees')
        self._require_device()
        self._device.MoveTo(self._decimal(angle), self._paddle(paddle), None)
        self.wait(paddle, timeout=timeout)

    def set_angles(self, angle1, angle2, angle3, timeout=None):
        """Move the three paddles sequentially and wait for each move to finish."""
        for paddle, angle in enumerate((angle1, angle2, angle3), start=1):
            self.move(paddle, angle, timeout=timeout)
