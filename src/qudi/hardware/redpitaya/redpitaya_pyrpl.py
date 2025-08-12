# filepath: c:\Users\yy3\GIT\squdi\src\qudi\hardware\redpitaya\redpitaya_pyrpl.py
# -*- coding: utf-8 -*-
"""
Red Pitaya hardware driver using PyRPL.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

from qudi.core.module import Base
import numpy as np
from pyrpl import Pyrpl
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.interface.redpitaya_interface import RedPitayaInterface
import time
from PySide2 import QtCore


class RedPitayaPyrpl(Base):
    """Hardware module for controlling Red Pitaya using PyRPL library."""

    # Config options - simplified to just IP address
    _config_file = ConfigOption('config_file', missing='warn')
    
    def __init__(self, config_file=None, **kwargs):
        if config_file :
            self._config_file = config_file
        super().__init__(**kwargs)

    def on_activate(self):
        """Initialize and connect to Red Pitaya device."""
        try:
            self._pyrpl = Pyrpl(config=self._config_file)
            self._rp = self._pyrpl.rp
            self._scope = self._rp.scope
            self._asg0 = self._rp.asg0
            self._asg1 = self._rp.asg1
            self._pid0 = self._rp.pid0
            self._pid1 = self._rp.pid1
            self._pid2 = self._rp.pid2

            self._iq0 = self._rp.iq0 
            self._iq1 = self._rp.iq1
            self._iq2 = self._rp.iq2

             
            
        except Exception as e:
            self.log.error(f'Failed to connect to Red Pitaya: {str(e)}')
            return None  # Qudi expects non-zero for failure

    def on_deactivate(self):
        # Best-effort: just drop references; PyRPL has no public disconnect
        try:
            self.stop_async_acquisition()
        except Exception:
            pass
        self._pyrpl = None
        self._rp = None
        self._scope = None
        self._asg0 = None
        self._asg1 = None
        self._pid0 = None
        self._pid1 = None
        self._pid2 = None

        self._iq0 = None 
        self._iq1 = None
        self._iq2 = None
