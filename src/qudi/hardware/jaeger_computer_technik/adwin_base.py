import os
import time
import numpy as np
from enum import Enum
from typing import Dict, Sequence, Tuple, List, Union
import ctypes

from ADwin import ADwin, ADwinError
from qudi.core import Base


class AdwinStatus(Enum):
    """Adwin Status"""

    EXECUTED = 0
    BASE_ERROR = -1


class AdwinProcessStatus(Enum):
    """Adwin Process Status"""

    RUNNING = 1
    NOT_RUNNING = 0
    ERROR = -1


class AdwinBase(Base):
    """
    Base class to use Adwin functionallities in Qudi.
    Every Hardware file using the Adwin should inharate from this parant class.
    """

    simulation_mode: bool = False

    def __init__(self, *args, **kwargs):
        """Get instance of ADwin and bootloader"""
        super().__init__(*args, **kwargs)

        # Connecting to dummy Adwin
        if self.simulation_mode:
            self.__adwin = AdwinDummy()

        # Connecting to real Adwin
        else:
            self.__adwin = ADwin(0x1, 1)
            self._device_name = "adwin11"
            self.btl: str = f"{self.__adwin.ADwindir}adwin11.btl"
        # TODO: Make process path part of config?

        self.__adwin_processes_path: str = os.path.join(
            os.path.dirname(__file__), "processes"
        )

    def on_activate(self) -> None:
        """on activation"""

    def on_deactivate(self) -> None:
        """on deactivation"""

    def boot_adwin(self, brut_force: bool = False) -> AdwinStatus:
        """Boots adwin"""

        adwin_status: int = self.__adwin.Test_Version()

        # Reboot adwin if adwin_status returns "error" or if "brut forced"
        if adwin_status != 0 or brut_force:
            self.__adwin.Boot(self.btl)
            self.log.info("Adwin rebooted :)")
            # TODO: Implement checks
            return AdwinStatus.EXECUTED

        reboot_required = True
        # Checks if Processes are currently running on the Adwin. If not -> reboot.
        for process_nr in range(1, 11):
            if self.__adwin.Process_Status(process_nr) == 1:
                reboot_required = False
                break

        # Reboot adwin
        if reboot_required:
            self.__adwin.Boot(self.btl)
            self.log.info("Adwin rebooted :)")
        # TODO: Implement checks
        return AdwinStatus.EXECUTED

    def start_adwin_processes(self, file_names: List[str], load_processes: bool = True) -> AdwinStatus:
        """Loads all specified adwin .tb_ files and starts the processes

        Args:
            list_file_names (List[str]): List of file names
        """
        for file_name in file_names:
            if load_processes:
                self.__adwin.Load_Process(
                    os.path.join(self.__adwin_processes_path, file_name)
                )

            int_adw_process_nr = (
                10 if int(file_name[-1]) == 0 else int(file_name[-1])
            )
            self.__adwin.Start_Process(int_adw_process_nr)
        # TODO: Implement checks
        return AdwinStatus.EXECUTED

    def stop_adwin_processes(self, file_names: List[str], clear_processes: bool = False) -> AdwinStatus:
        """Stops and clears all specified adwin processes

        Args:
            list_file_names (List[str]): List of file names
        """
        for file_name in file_names:
            int_adw_process_nr = 10 if int(file_name[-1]) == 0 else int(file_name[-1])
            self.__adwin.Stop_Process(int_adw_process_nr)
            if clear_processes:
                self.__adwin.Clear_Process(int_adw_process_nr)
        # TODO: Implement checks
        return AdwinStatus.EXECUTED

    def check_adw_process_status(
        self, adw_process_file_name: str
    ) -> AdwinProcessStatus:
        """Checks the state of an adwin process"""
        adw_process_nr = (
            10
            if int(adw_process_file_name[-1]) == 0
            else int(adw_process_file_name[-1])
        )
        adw_status = self.__adwin.Process_Status(adw_process_nr)

        if adw_status == 1:
            return AdwinProcessStatus.RUNNING
        elif adw_status == 0:
            return AdwinProcessStatus.NOT_RUNNING
        else:
            return AdwinProcessStatus.ERROR

    def write_fpar(self, idx: int, value: float) -> AdwinStatus:
        """Set fpar

        Args:
            idx (int): index of fpar
            value (float): Value set to fpar

        Returns:
            AdwinStatus: State of adwin
        """
        try:
            self.__adwin.Set_FPar(idx, value)
        except ADwinError as e:
            self.log.error(f"Could not set Fpar. Error:\n\n {e}")
            return AdwinStatus.BASE_ERROR

        return AdwinStatus.EXECUTED

    def write_par(self, idx: int, value: int) -> AdwinStatus:
        """Set Par

        Args:
            idx (int): index of par
            value (int): Value set to par

        Returns:
            AdwinStatus: State of adwin
        """
        try:
            self.__adwin.Set_Par(idx, value)
            print(idx)
        except ADwinError as e:
            self.log.error(f"Could not set Par. Error:\n\n {e}")
            return AdwinStatus.BASE_ERROR

        return AdwinStatus.EXECUTED

    def write_data_float(
        self,
        pc_array: Union[list, np.ndarray],
        data_no: int,
        start_idx: int,
        count: int,
    ) -> AdwinStatus:
        """SetData_Float transfers float values of 32 bit precision into a DATA array of the ADwin hardware.

        Args:
            pc_array (Union[list, np.ndarray]): Source array, from which data are transferred.
            data_no (int): Number (1...200) of destination array DATA_1 … DATA_200.
            start_idx (int): Number (≥1) of the first element in the destination array,into which data is transferred.
            count (int): Number (≥1) of values to be transferred.

        Returns:
            AdwinStatus: Adwin error code
        """
        try:
            self.__adwin.SetData_Float(pc_array, data_no, start_idx, count)
        except ADwinError as e:
            self.log.error(f"Could not set Data Float. Error:\n\n {e}")
            return AdwinStatus.BASE_ERROR

        return AdwinStatus.EXECUTED

    def read_par(self, idx: int) -> tuple[Union[float, None], AdwinStatus]:
        """Get Par

        Args:
            idx (int): Index of Par

        Returns:
            Union[int, AdwinStatus]: Value of Par or error code
        """
        try:
            value: int = self.__adwin.Get_Par(idx)
        except ADwinError as e:
            self.log.error(f"Could not set Par. Error:\n\n {e}")
            return None, AdwinStatus.BASE_ERROR

        return value, AdwinStatus.EXECUTED

    def read_fpar(self, idx: int) -> tuple[Union[float, None], AdwinStatus]:
        """Get Par

        Args:
            idx (int): Index of Par

        Returns:
            Union[float, AdwinStatus]: Value of Par or error code
        """
        try:
            value: float = self.__adwin.Get_FPar(idx)
        except Exception as e:
            self.log.error(f"Could not set Par. Error:\n\n {e}")
            return None, AdwinStatus.BASE_ERROR

        return value, AdwinStatus.EXECUTED


class AdwinDummy:

    def __init__(self) -> None:
        pass

    @staticmethod
    def Get_FPar(idx: int) -> float:
        """Simulates Get_Fpar, returns always 0"""
        return 0.0

    @staticmethod
    def Get_Par(idx: int) -> int:
        """Simulates Get_Par, returns always 0"""
        return 0

    @staticmethod
    def Set_FPar(idx: int, vlaue: float) -> None:
        """Simulates Set_FPar, doesn't do anything"""

    @staticmethod
    def Set_Par(idx: int, vlaue: int) -> None:
        """Simulates Set_Par, doesn't do anything"""

    @staticmethod
    def SetData_Float(pc_array, data_no, start_idx, count) -> None:
        """Simulates SetData_Float, doesn't do anything"""

    @staticmethod
    def Process_Status(process_no: int) -> int:
        """Simulates Process_Status, always returns 1 (Running)"""
        return 1

    @staticmethod
    def Stop_Process(process_no: int) -> None:
        """Simulates Stop_Process, doesn't do anything"""

    @staticmethod
    def Clear_Process(process_no: int) -> None:
        """Simulates Clear_Process, doesn't do anything"""

    @staticmethod
    def Boot(filename: str) -> None:
        """Simulates Boot, doesn't do anything"""

    @staticmethod
    def Test_Version() -> int:
        """Simulates Test_Version, returns always 0"""
        return 0

    @staticmethod
    def Start_Process(process_no: int) -> None:
        """Simulates Start_Process, doesn't do anything"""

    @staticmethod
    def Load_Process(process_no: int) -> None:
        """Simulates Load_Process, doesn't do anything"""
