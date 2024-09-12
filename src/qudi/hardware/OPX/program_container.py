import qm

"""
This is a moku of MCAS basic functions for program to have some object oriented stuff. 
"""

class MultiChSeq():

    def __init__(self, name, qm):
        self._name = name
        self._qm = qm

    @property
    def name(self):
        return self._name

    @property
    def program(self):
        return self._program

    @program.setter
    def program(self, val):
        self._program = val

    @property
    def qm(self):
        """
        Quantum machine instance, obtained as QuantumMachineManager.open_qm method
        :return:
        """
        return self._qm

    def initialize(self):
        """
        Runs the programm.
        :return:
        """
        job = self.qm.execute(self.program)

    @property
    def job(self):

        return self._job