'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 1
' Initial_Processdelay           = 3000
' Eventsource                    = Timer
' Control_long_Delays_for_Stop   = No
' Priority                       = Low
' Priority_Low_Level             = 1
' Version                        = 1
' ADbasic_Version                = 6.3.1
' Optimize                       = Yes
' Optimize_Level                 = 1
' Stacksize                      = 1000
' Info_Last_Save                 = QINU  QINU\yy3
'<Header End>
#Include ADwinGoldII.inc

Dim data_1[1000000] as Float
Dim data_2[1000000] as Float
Dim data_3[1000000] as Float
'Dim data_4[10000] as Float' # legacy for PLE?
Dim index as Long     
Dim rise_time as Long
Dim low_time as Long
Dim total_time as Long



Function get_vol(input) As Long   'input is in m'   
  Dim vol as Float
  vol = input'(1.0/0.07853981633) * arctan(input/2.1e-3) - 0.3 'Volts'
  If (AbsF(vol) > 5) Then
    get_vol = 32768
  Else
    get_vol = vol * 3277 + 32768 'Bits'
  EndIf
EndFunction

Function get_vol_z(input_z) As Long      
  Dim vol2 as Float
  vol2 = input_z'(input_z/3)*10e5'
  If ((vol2 > 9.5) OR (vol2 < -5)) Then
    get_vol_z = 32768
  Else
    get_vol_z = vol2 * 3277 + 32768 'Bits'
  EndIf

EndFunction
  
Init:
  rise_time = 0.25*PAR_20
  low_time = 0.75*PAR_20
  total_time = PAR_20
  Digout(9, 0)
Event:  
  For index = 1 To PAR_21
    DAC(1, get_vol(data_1[index]))
    DAC(2, get_vol(data_2[index]))
    DAC(3, get_vol_z(data_3[index]))
    If (PAR_22 = 1) Then
      Digout(9, 0) 'TTL' - timetagger.we need to switch to the DO
      CPU_Sleep(rise_time)
      Digout(9, 1)
      CPU_Sleep(low_time)
    Else
      CPU_Sleep(total_time)
    EndIf
  Next
  CPU_Sleep(100)
  End
  
Finish:
  Digout(9, 0)
