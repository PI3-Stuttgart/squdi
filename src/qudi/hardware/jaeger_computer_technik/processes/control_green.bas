'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 2
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
Dim data_5[10000] as Float
Init:
  CONF_DIO(1111b)
  
Event:
  If (data_5[1] = 1.0) Then
    Digout(3,1)
    
  Else
    Digout(3,0)
   
  EndIf
  
  If (data_5[2] = 1.0) Then
    Digout(7,1)
    
  Else
    Digout(7,0)
    
  EndIf
  
  If (data_5[3] = 1.0) Then
    Digout(0,1)
    
  Else
    Digout(0,0)
    
  EndIf
Finish:
  
