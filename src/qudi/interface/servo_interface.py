# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod
from typing import Sequence, Tuple, Dict, Optional


# Do NOT inherit qudi.core.module.Base here — keep a plain abstract interface
class servo_interface(ABC):
    """Interface for controlling servo motors (serial/usb controllers)."""

    @property
    @abstractmethod
    def constraints(self) -> Dict:
        """Return a dict-like constraints object describing limits and available servos."""
        raise NotImplementedError

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the hardware connection is active."""
        raise NotImplementedError

    @abstractmethod
    def send_position(self, servo_id: str, position: float) -> None:
        """Send a position command to the servo with id servo_id."""
        raise NotImplementedError

    @abstractmethod
    def get_last_position(self, servo_id: str) -> Optional[float]:
        """Return the last known position for servo_id or None if unknown."""
        raise NotImplementedError

    @abstractmethod
    def get_available_servos(self) -> Sequence[str]:
        """Return a sequence of available servo ids (strings)."""
        raise NotImplementedError

    @abstractmethod
    def get_position_limits(self, servo_id: str) -> Tuple[Optional[float], Optional[float]]:
        """Return (min, max) position limits for the given servo_id (None if not set)."""
