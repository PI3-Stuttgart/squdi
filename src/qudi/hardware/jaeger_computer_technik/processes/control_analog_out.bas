'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 9
' Initial_Processdelay           = 3000
' Eventsource                    = Timer
' Control_long_Delays_for_Stop   = No
' Priority                       = High
' Version                        = 1
' ADbasic_Version                = 6.3.1
' Optimize                       = Yes
' Optimize_Level                 = 1
' Stacksize                      = 1000
' Info_Last_Save                 = QINU  QINU\yy3
'<Header End>
#Include ADwinGoldII.inc

Dim curr_volt_port_7 As Float
Dim curr_volt_port_8 As Float

Function volt2bit(volt_in) As Long      
  If ((volt_in < 0) OR (volt_in > 5)) Then
    volt2bit = 32768
  Else
    volt2bit = volt_in * 3277 + 32768 'Bits'
  EndIf
EndFunction

  
Init:
  Conf_DIO(1111b)
  curr_volt_port_7 = 0
  DAC(7, volt2bit(0)) 
  curr_volt_port_7 = FPar_7
  
  curr_volt_port_8 = 0
  DAC(8, volt2bit(0)) 
  curr_volt_port_8 = FPar_8
Event:  
  If (curr_volt_port_7 <> FPar_7) Then
    DAC(7, volt2bit(FPar_7))  
    curr_volt_port_7 = FPar_7
  EndIf
  
  If (curr_volt_port_8 <> FPar_8) Then
    DAC(8, volt2bit(FPar_8))  
    curr_volt_port_8 = FPar_8
  EndIf
  
Finish:

  
