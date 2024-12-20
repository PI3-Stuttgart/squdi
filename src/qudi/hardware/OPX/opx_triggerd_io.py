from qudi.interface.triggered_ao_interface import TriggeredAOInterface
from qudi.core.configoption import ConfigOption
from typing import Iterable, Mapping, Union, Optional, Tuple, Type, Dict


class QMLaserScanner(TriggeredAOInterface):
    """Example config for copy-paste:

    QMLaserScanner:
        module.Class: 'OPX.toptica_dl_pro.QMLaserScanner'
        connect:
            OPX: "OPX"
            AO_OPX = "AO_OPX"
        options:
            _trigger_channel = "Gate_Trigger"
            _laser_scanning_channel = "LaserScanner_red"
    """

    OPX = Connector(interface='OPX')
    AO_OPX = Connector(interface='AO_OPX')

    _trigger_channel = ConfigOption(name="trigger_channel", default='Gate_Trigger', missing="nothing")
    _laser_scanning_channel = ConfigOption(name="laser_scanning_channel", default='LaserScanner_red', missing="nothing")


    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

