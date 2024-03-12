
from PySide2 import QtCore, QtGui, QtWidgets
import qudi.util.uic as uic
import os
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox
import pyqtgraph as pg

class PlePulsedWidget(QtWidgets.QWidget):
    sig_pulser_params_updated = QtCore.Signal(dict)
    sig_prescan_repump = QtCore.Signal(bool)

    def __init__(self, name, *args, **kwargs):
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'pulsed_widget.ui')
        super(PlePulsedWidget, self).__init__(*args, **kwargs)
        uic.loadUi(ui_file, self)

        self.RepumpLengthdoubleSpinBox.setDecimals(3)
        self.RepumpLengthdoubleSpinBox.setSuffix('s')

        self.RepumpDelaydoubleSpinBox.setDecimals(3)
        self.RepumpDelaydoubleSpinBox.setSuffix('s')

        self.ResonantLengthDoubleSpinBox.setDecimals(3)
        self.ResonantLengthDoubleSpinBox.setSuffix('s')

        self.ResonantPeriodDoubleSpinBox.setDecimals(3)
        self.ResonantPeriodDoubleSpinBox.setSuffix('s')

        self.PulserupdatePushButton.pressed.connect(self.update_params)

        self.prescan_checkBox.toggled.connect(
            lambda: self.sig_prescan_repump.emit(self.prescan_checkBox.isChecked())
        )
        


        self.set_constraints()

    def update_params(self):
        params = {
        "resonant":
            {   
                "length" : self.ResonantLengthDoubleSpinBox.value(),
                "period" : self.ResonantPeriodDoubleSpinBox.value(),
            },
        "repump":
            {   
                "length" : self.RepumpLengthdoubleSpinBox.value(),
                "delay"  : self.RepumpDelaydoubleSpinBox.value(),
                "repeat"  : self.RepeatRepumpSpinBox.value(),
            }
        }
        self.sig_pulser_params_updated.emit(params)
    
    def update_gui(self, params):
        self.ResonantLengthDoubleSpinBox.setValue(params['resonant']['length'])
        self.ResonantPeriodDoubleSpinBox.setValue(params['resonant']['period'])
        self.RepumpLengthdoubleSpinBox.setValue(params['repump']['length'])
        self.RepumpDelaydoubleSpinBox.setValue(params['repump']['delay'])
        self.RepeatRepumpSpinBox.setValue(params['repump']['repeat'])

    def set_constraints(self, constraints=None):
        # #TODO get pulse streamer constraints
        # self.LengthDoubleSpinBox.setRange(*(0, 5))
        # self.LengthDoubleSpinBox.setDecimals(1)
        # self.LengthDoubleSpinBox.setSuffix('s')

        # self.PeriodDoubleSpinBox.setRange(*(0, 5))
        # self.PeriodDoubleSpinBox.setDecimals(1)
        # self.PeriodDoubleSpinBox.setSuffix('s')

        # #TODO get power constraints
        # self.PowerDoubleSpinBox.setRange(*(0.0, 1.0))
        # self.PowerDoubleSpinBox.setSuffix(' ')#'μW')
        # self.PowerDoubleSpinBox.setDecimals(1)

        # #TODO get pulse streamer constraints
        # self.LengthDoubleSpinBox.setRange(*(0, 5))
        # self.LengthDoubleSpinBox.setDecimals(1)
        # self.LengthDoubleSpinBox.setSuffix('s')

        # self.DelayDoubleSpinBox.setRange(*(0, 5))
        # self.DelayDoubleSpinBox.setDecimals(1)
        # self.DelayDoubleSpinBox.setSuffix('s')

        # #TODO get power constraints
        # self.PowerDoubleSpinBox.setRange(*(0.0, 1.0))
        # self.PowerDoubleSpinBox.setDecimals(1)
        # self.PowerDoubleSpinBox.setSuffix(' ')#'μW')
        pass

class PleMicrowaveWidget(QtWidgets.QWidget):
    sig_microwave_params_updated = QtCore.Signal(float, float)
    sig_microwave_enabled = QtCore.Signal(bool)

    params = {}
    def __init__(self, *args, **kwargs):
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'microwave_widget.ui')
        super(PleMicrowaveWidget, self).__init__(*args, **kwargs)
        uic.loadUi(ui_file, self)
        
        self.enabledCheckBox.toggled.connect(
            lambda: self.sig_microwave_enabled.emit(self.enabledCheckBox.isChecked())
        )
        self.FreqDoubleSpinBox.editingFinished.connect(
            lambda: self.sig_microwave_params_updated.emit(self.FreqDoubleSpinBox.value(), self.PowerDoubleSpinBox.value())
        )
        self.PowerDoubleSpinBox.editingFinished.connect(
            lambda: self.sig_microwave_params_updated.emit(self.FreqDoubleSpinBox.value(), self.PowerDoubleSpinBox.value())
        )
  
    @QtCore.Slot(dict)
    def update_params(self, params):
        self.FreqDoubleSpinBox.setValue(params['frequency'])
        self.PowerDoubleSpinBox.setValue(params['power'])
        
    @QtCore.Slot(bool)
    def enable_microwave(self, enabled):
        self.enabledCheckBox.setChecked(enabled)

    def set_constraints(self, constraints):
        self.FreqDoubleSpinBox.setRange(*constraints.frequency_limits)
        # self.FreqDoubleSpinBox.setDecimals(6)
        self.FreqDoubleSpinBox.setSuffix('Hz')

        self.PowerDoubleSpinBox.setRange(*constraints.power_limits)
        self.PowerDoubleSpinBox.setSuffix('dBm')