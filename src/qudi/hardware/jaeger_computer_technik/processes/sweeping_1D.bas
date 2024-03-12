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
' Info_Last_Save                 = DESKTOP-O5HD7AV  DESKTOP-O5HD7AV\yy3
'<Header End>
#Include ADwinGoldII.inc

Dim data_1[10000] as Float
Dim data_2[10000] as Float
Dim data_3[10000] as Float
Dim data_4[10000] as Float
Dim index as Long     
Dim rise_time as Long

Function get_vol(input) As Long      
  Dim vol as Float
  vol = (1.0/0.07853981633) * arctan(input/2.1e-3) - 0.3 'Volts'
  If (AbsF(vol) > 5) Then
    get_vol = 32768
  Else
    get_vol = vol * 3277 + 32768 'Bits'
  EndIf
EndFunction

Function get_vol_z(input_z) As Long      
  Dim vol2 as Float
  vol2 = (input_z/3)*10e5
  If ((vol2 > 9.5) OR (vol2 < -5)) Then
    get_vol_z = 32768
  Else
    get_vol_z = vol2 * 3277 + 32768 'Bits'
  EndIf

EndFunction
  
Init:
  
Event:  
  rise_time = 0.25*PAR_20
  For index = 1 To PAR_21
    DAC(1, get_vol(data_1[index]))
    DAC(2, get_vol(data_2[index]))
    DAC(6, get_vol_z(data_3[index]))
    If (PAR_22 = 1) Then
      DAC(7,40000)
      CPU_Sleep(rise_time)
      DAC(7,32768) 
      CPU_Sleep(PAR_20)
    Else
      CPU_Sleep(PAR_20)
    EndIf
  Next
  CPU_Sleep(100)
  End
  
Finish:

