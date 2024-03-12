# -*- coding: utf-8 -*-

import os

from serial import Serial, EIGHTBITS,STOPBITS_ONE,PARITY_NONE


class ThorlabsElloRotation():	
	double_revelation = 286722 # bullshit specs number: 262144
	revelation = int(double_revelation/2)

	def __init__(self, serial_port, port, ell=None):
		self._port = port
		self._serial_port = serial_port
		if ell is None:
			self.connect()
		else:
			self.ell = ell

	def connect(self):
		""" Connects to the stage.
		"""
		self.ell = Serial(self._serial_port, baudrate=9600, bytesize=EIGHTBITS, stopbits=STOPBITS_ONE,parity= PARITY_NONE, timeout=2)

	def get_info(self):
		self.ell.write(bytes(f"{self._port}in", 'ascii'))
		return self.ell.read(32)

	def disconnect(self):
		""" Disconnects from the stage.
		"""
		self.ell.close()

	def home(self):
		""" Homes the rotation mount.
		"""
		self.ell.write(bytes(f"{self._port}ho0", 'ascii'))
		self.ell.read(32)

	def get_home_pos(self):
		""" Returns the homing position (angel in degree) of the device.
		"""
		self.ell.write(bytes(f"{self._port}go", 'ascii'))
		pos16 = self.ell.read(32)
		pos10 = int("".join(filter(lambda x: x not in "brn\\'", str(pos16)))[3:], 16)
		#revelation = 262144
		angle = 360 * pos10 / self.revelation
		return angle

	def set_home_pos(self,angle):
		"""Changes the home position to the specified angle.
		
		It is good practice to record the factory set home offset before changing it. 
		This way one can ensure that all ello devices home the same and can be reset in case of problems.
		"""
		to_pos10 = int(angle * (self.revelation/ 360))
		to_pos16 = str(hex(to_pos10))[2:].upper().zfill(8)
		command = bytes(f"{self._port}so{to_pos16}", 'ascii')
		self.ell.write(command)
		return

	def get_pos(self):
		""" Returns the current position of the stage. In degree angle
		"""
		self.ell.write(bytes(f"{self._port}gp", 'ascii'))
		pos16 = self.ell.read(32)
		pos10 = int("".join(filter(lambda x: x not in "brn\\'", str(pos16)))[3:], 16)
		#revelation = 262144
		angle = 360 * pos10 / self.revelation
		return angle

	def move_abs(self, to_angle):
		""" Moves stage to absolute position.
		"""
		to_pos10 = int(to_angle * (self.revelation/ 360))
		to_pos16 = str(hex(to_pos10))[2:].upper().zfill(8)
		command = bytes(f"{self._port}ma{to_pos16}", 'ascii')
		self.ell.write(command)

	def move_rel(self, angle):
		""" Moves stage by relative angle.
		"""
		to_pos10 = int(angle * (self.revelation/ 360))
		to_pos16 = str(hex(to_pos10))[2:].upper().zfill(8)
		command = bytes(f"{self._port}mr{to_pos16}", 'ascii')
		self.ell.write(command)

	def get_jog_size(self):
		self.ell.write(bytes(f"{self._port}gj", 'ascii'))
		#return self.ell.read(32)
		pos16 = self.ell.read(32)
		pos10 = int("".join(filter(lambda x: x not in "brn\\'", str(pos16)))[3:], 16)
		#revelation = 262144
		angle = 360 * pos10 / self.revelation
		return angle

	def set_jog_size(self, angle):
		to_pos10 = int(angle * (self.revelation/ 360))
		to_pos16 = str(hex(to_pos10))[2:].upper().zfill(8)
		command = bytes(f"{self._port}sj{to_pos16}", 'ascii')
		self.ell.write(command)

	def move_forward(self):
		self.ell.write(bytes(f"{self._port}fw", 'ascii'))
		return self.ell.read(32)

	def move_backward(self):
		self.ell.write(bytes(f"{self._port}bw", 'ascii'))
		return self.ell.read(32)