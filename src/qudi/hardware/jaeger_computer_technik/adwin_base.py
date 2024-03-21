from qudi.core import Base
import os
import ADwin
from typing import Dict, Mapping, Sequence, Tuple, List

class AdwinBase(Base):
    
    def __init__(self, *args, **kwargs):
        """Get instance of ADwin adn bootloader 
        """
        super().__init__(*args, **kwargs)
        self.adwin = ADwin.ADwin(0x1, 1)
        self._device_name = 'adwin11'
        self.btl = f'{self.adwin.ADwindir}adwin11.btl'
        # TODO: Make process path part of config?
        self.adwin_processes_path = os.path.join(
            os.path.dirname(__file__), 'processes')
    
    
    def on_activate(self):
        """Checks if the adwin is booted and boots it. 
        """
        # TODO
        pass 
        
        
    def on_deactivate(self):
        # TODO 
        pass
    
    
    def boot_adwin(self):
        """Boots adwin
        """
        self.adwin.Boot(self.btl)
        
        
    def start_adwin_processes(self, list_file_names:List[str]):
        """Loads all specified adwin .tb_ files and starts the processes

        Args:
            list_file_names (List[str]): List of file names
        """ 
        for str_file_name in list_file_names:
            self.adwin.Load_Process(
                os.path.join(self.adwin_processes_path, str_file_name))
            
            int_adw_process_nr = 10 if int(str_file_name[-1]) == 0 else int(str_file_name[-1])
            self.adwin.Start_Process(int_adw_process_nr)
            
    
    
    def reset_hardware(self): ##SHOULDNT IT BE IN ADWIN BASE?
        self.stop_all()
        self.boot_adwin()
        return 1