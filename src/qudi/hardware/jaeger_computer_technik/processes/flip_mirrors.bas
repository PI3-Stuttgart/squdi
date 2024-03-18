'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 4
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

Dim curr_pos As Long
Init:
  curr_pos = 0
  Par_30 = 0
 
Event:
  If (Par_30 <> curr_pos) Then
    Digout(7,1)
    IO_sleep(1000000)
    Digout(7,0)
    curr_pos = Par_30
  EndIf
Finish:
  If (curr_pos = 1) Then
    Digout(7,1)
    IO_Sleep(1000000)
    Digout(7,0)   
  EndIf
  
