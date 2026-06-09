import os
from PySide2 import QtCore, QtWidgets
from qudi.core.connector import Connector
from qudi.core.module import GuiBase

class RedPitayaPyrplGui(GuiBase):
    """Qudi GUI wrapper for PyRPL main widget."""

    # Connectors
    _redpitaya_logic = Connector(name='redpitaya_logic', interface='RedPitayaPyrplLogic')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None

    def on_activate(self):
        """Initialize the GUI on activation."""
        logic = self._redpitaya_logic()
        if logic is None:
            raise RuntimeError("RedPitaya logic connector is not available.")
            
        pyrpl_instance = logic.get_pyrpl()
        if pyrpl_instance is None:
            raise RuntimeError("PyRPL instance is not available from logic module.")

        # Check if the pyrpl_instance is a remote proxy (using rpyc)
        is_remote = hasattr(pyrpl_instance, '___conn___') or type(pyrpl_instance).__name__ in ('netref', 'BaseNetref')

        if is_remote:
            # We are running on a remote client PC. 
            # We must instantiate the PyrplWidget locally, but passing the remote pyrpl proxy.
            # We must ensure the sub-widgets are also created locally.
            from pyrpl.widgets.pyrpl_widget import PyrplWidget
            import pyrpl.widgets.module_widgets
            
            # Subclass PyrplWidget to override dock widget creation for remote compatibility
            class RemotePyrplWidget(PyrplWidget):
                def __init__(self, pyrpl_instance):
                    # Call QMainWindow constructor and initialize local state
                    QtWidgets.QMainWindow.__init__(self)
                    self.parent = pyrpl_instance
                    self.logger = self.parent.logger
                    
                    self.setDockNestingEnabled(True)
                    self.setAnimated(True)
                    self.dock_widgets = {}
                    self.last_docked = None
                    
                    self.menu_modules = self.menuBar().addMenu("Modules")
                    self.module_actions = []
                    
                    # For each software module, get its local widget class and instantiate it locally
                    for module in self.parent.software_modules:
                        widget_class_name = module._widget_class.__name__
                        local_widget_class = getattr(pyrpl.widgets.module_widgets, widget_class_name)
                        
                        def make_create_widget_func(m, cls):
                            return lambda: cls(m.name, m)
                            
                        local_create_fn = make_create_widget_func(module, local_widget_class)
                        self.add_dock_widget(local_create_fn, module.name)
                        
                    self.centralwidget = QtWidgets.QFrame()
                    self.setCentralWidget(self.centralwidget)
                    self.centrallayout = QtWidgets.QVBoxLayout()
                    self.centrallayout.setAlignment(QtCore.Qt.AlignCenter)
                    self.centralwidget.setLayout(self.centrallayout)
                    self.centralbutton = QtWidgets.QPushButton(
                        'Click on "Modules" in the upper left corner to load a specific PyRPL module!'
                    )
                    self.centralbutton.clicked.connect(self.click_menu_modules)
                    self.centrallayout.addWidget(self.centralbutton)
                    
                    self.timer_save_pos = QtCore.QTimer()
                    self.timer_toolbar = QtCore.QTimer()
                    self.status_bar = self.statusBar()
                    self.setWindowTitle(f"{self.parent.c.pyrpl.name} (Remote)")
            
            self._mw = RemotePyrplWidget(pyrpl_instance)
        else:
            # We are running locally on the server PC. 
            if len(pyrpl_instance.widgets) == 0:
                self._mw = pyrpl_instance._create_widget()
            else:
                self._mw = pyrpl_instance.widgets[0]

        # Show the main window
        self.show()

    def on_deactivate(self):
        """Clean up before deactivating module."""
        if self._mw is not None:
            try:
                self._mw.close()
            except Exception:
                pass
            self._mw = None

    def show(self):
        """Show the main window."""
        if self._mw is not None:
            self._mw.show()
            self._mw.raise_()