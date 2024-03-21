'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 5
' Initial_Processdelay           = 3000
' Eventsource                    = Timer
' Control_long_Delays_for_Stop   = No
' Priority                       = High
' Version                        = 1
' ADbasic_Version                = 6.3.1
' Optimize                       = Yes
' Optimize_Level                 = 1
' Stacksize                      = 1000
' Info_Last_Save                 = DESKTOP-O5HD7AV  DESKTOP-O5HD7AV\yy3
'<Header End>
#Include ADwinGoldII.inc

Dim curr_attenuation As Float
Function volt2bit(volt_in) As Long      
  If ((volt_in < 0) OR (volt_in > 5)) Then
    volt2bit = 32768
  Else
    volt2bit = volt_in * 3277 + 32768 'Bits'
  EndIf
EndFunction

  
Init:
  FPar_30 = 5
  curr_attenuation = FPar_30
  DAC(5, volt2bit(FPar_30)) 
Event:  
  If (curr_attenuation <> FPAR_30) Then
    DAC(5, volt2bit(FPar_30))  
  EndIf
  
Finish:
