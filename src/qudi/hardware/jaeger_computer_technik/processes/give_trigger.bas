'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 1
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
' PAR 30: 0 stopped, 1 start/running
' PAR 31: Number of pulses before stopping
' PAR 32: Current pulse count
' PAR 33: Digital output port number

' FPAR30: sample rate

Dim pulse_length as Long
Init:
  pulse_length = 99
  
  FPAR_30 = 1000
Event:
  Processdelay = 1/FPAR_30*3*10^8
  
  ' Check if defined number of pulses is not yet reached
  If (PAR_32 <= PAR_31)  Then
    ' Check if process is aborted or not
    If (PAR_30 = 1) Then
      ' set didital output pulse
      Digout(PAR_33, 1)
      CPU_Sleep(pulse_length)
      Digout(PAR_33, 0)
      ' count pulses
      PAR_32 = FPAR_32 + 1
    EndIf
  Else
    PAR_30 = 0
    PAR_32 = 0 
  EndIf
  
  
Finish:
