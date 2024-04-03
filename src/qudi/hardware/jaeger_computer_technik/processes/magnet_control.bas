'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 2
' Initial_Processdelay           = 300003000
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
Dim meas_bit_x as Long
Dim meas_bit_y as Long
Dim meas_bit_z as Long

Dim diff_bit_x as Long
Dim diff_bit_y as Long
Dim diff_bit_z as Long

Dim volt_step as Float
Dim bit_step as Long

Dim max_meas_diff_volt as Float
Dim max_meas_diff_bit as Long

Dim step_freq as Float

Dim meas_offset_x_volt as Float
Dim meas_offset_y_volt as Float
Dim meas_offset_z_volt as Float

Dim meas_offset_x_bit as Long
Dim meas_offset_y_bit as Long
Dim meas_offset_z_bit as Long

Dim bit_step_final as Long
Dim max_meas_diff_bit_final as Long

Dim bit_curr_out_x as Long
Dim bit_curr_out_y as Long
Dim bit_curr_out_z as Long

Function volt2bit(input) As Long 
  If (AbsF(input)<10) Then     
    volt2bit = input * 3277 + 32768 
  Else
    volt2bit = 32768
  EndIf
EndFunction

Function bit2volt(input) As Float     
  bit2volt = (input-32768)/3277 
EndFunction
  
Init:
  If ((FPar_13 > 0.05) OR (FPAR_13 <= 0)) Then
    volt_step = 0.015
  Else
    volt_step = FPar_13
  EndIf
  
  bit_step = volt_step * 3277
  
  bit_step_final = 0.002 * 3277
  
  If ((FPar_14 > 100) OR (FPAR_14 <= 0)) Then
    processdelay = 1 * 300003000
  Else
    processdelay = 1/FPar_14 * 300003000
  EndIf
  
  max_meas_diff_volt = volt_step / 2
  max_meas_diff_bit = max_meas_diff_volt * 3277
  
  max_meas_diff_bit_final = 0.005 * 3277
  
  meas_offset_x_volt = -0.004
  meas_offset_y_volt = 0.004
  meas_offset_z_volt = 0.002
  
  meas_offset_x_bit = meas_offset_x_volt * 3277
  meas_offset_y_bit = meas_offset_y_volt * 3277
  meas_offset_z_bit = meas_offset_z_volt * 3277
  
  bit_curr_out_x = ADC(1) - meas_offset_x_bit
  bit_curr_out_y = ADC(2) - meas_offset_x_bit
  bit_curr_out_z = ADC(3) - meas_offset_x_bit
  
Event: 

  If ((FPar_14 > 100) OR (FPAR_14 <= 0)) Then
    processdelay = 1 * 300003000
  Else
    processdelay = 1/FPar_14 * 300003000
  EndIf 
 
  meas_bit_x = ADC(1) - meas_offset_x_bit
  meas_bit_y = ADC(2) - meas_offset_y_bit
  meas_bit_z = ADC(3) - meas_offset_z_bit
  
  
  If (abs(meas_bit_x - bit_curr_out_x) > 0.005 * 3277) Then
    bit_curr_out_x = meas_bit_x 
  Endif
  
  If (abs(meas_bit_y - bit_curr_out_y) > 0.005 * 3277) Then
    bit_curr_out_y = meas_bit_y 
  Endif
  
  If (abs(meas_bit_z - bit_curr_out_z) > 0.005 * 3277) Then
    bit_curr_out_z = meas_bit_z
  Endif
  
  'diff_bit_x = Abs(meas_bit_x - volt2bit(FPAR_10))
  'diff_bit_y = Abs(meas_bit_y - volt2bit(FPAR_11))
  'diff_bit_z = Abs(meas_bit_z - volt2bit(FPAR_12))

  REM X-Achse
  'If ((meas_bit_x + max_meas_diff_bit) < volt2bit(FPAR_10)) Then
  '  DAC(4, meas_bit_x + bit_step)
  'EndIf
  
  'If ((meas_bit_x - max_meas_diff_bit) > volt2bit(FPAR_10)) Then
  '  DAC(4, meas_bit_x - bit_step)
  'EndIf

  'REM Y-Achse
  'If ((meas_bit_y + max_meas_diff_bit) < volt2bit(FPAR_11)) Then
  '  DAC(5, meas_bit_y + bit_step)
  'EndIf
  
  'If ((meas_bit_y - max_meas_diff_bit) > volt2bit(FPAR_11)) Then
  '  DAC(5, meas_bit_y - bit_step)
  'EndIf
  
  REM Z-Achse
  
  'If ((meas_bit_z + max_meas_diff_bit) < volt2bit(FPAR_12)) Then
  '  DAC(6, meas_bit_z + bit_step)
  'EndIf
  
  'If ((meas_bit_z - max_meas_diff_bit) > volt2bit(FPAR_12)) Then
  '  DAC(6, meas_bit_z - bit_step)
  'EndIf
 
  REM X- Achse
  If(abs(meas_bit_x - volt2bit(FPAR_10)) > max_meas_diff_bit ) Then
    If (meas_bit_x < volt2bit(FPAR_10)) Then
      DAC(4, bit_curr_out_x + bit_step)
      bit_curr_out_x = bit_curr_out_x + bit_step
    Endif
    
    If (meas_bit_x > volt2bit(FPAR_10)) Then
      DAC(4, bit_curr_out_x - bit_step)
      bit_curr_out_x = bit_curr_out_x - bit_step
    Endif
    
  Else
    If(abs(meas_bit_x - volt2bit(FPAR_10)) > max_meas_diff_bit_final ) Then
      If (meas_bit_x < volt2bit(FPAR_10)) Then
        DAC(4, bit_curr_out_x + bit_step_final)
        bit_curr_out_x = bit_curr_out_x + bit_step_final
      Endif
    
      If (meas_bit_x > volt2bit(FPAR_10)) Then
        DAC(4, bit_curr_out_x - bit_step_final)
        bit_curr_out_x = bit_curr_out_x - bit_step_final
      Endif
    Endif    
  Endif
  
  REM Y- Achse
  If(abs(meas_bit_y - volt2bit(FPAR_11)) > max_meas_diff_bit ) Then
    If (meas_bit_y < volt2bit(FPAR_11)) Then
      DAC(5, bit_curr_out_y + bit_step)
      bit_curr_out_y = bit_curr_out_y + bit_step
    Endif
    
    If (meas_bit_y > volt2bit(FPAR_11)) Then
      DAC(5, bit_curr_out_y - bit_step)
      bit_curr_out_y = bit_curr_out_y - bit_step
    Endif
    
  Else
    If(abs(meas_bit_y - volt2bit(FPAR_11)) > max_meas_diff_bit_final ) Then
      If (meas_bit_y < volt2bit(FPAR_11)) Then
        DAC(5, bit_curr_out_y + bit_step_final)
        bit_curr_out_y = bit_curr_out_y + bit_step_final
      Endif
    
      If (meas_bit_y > volt2bit(FPAR_11)) Then
        DAC(5, bit_curr_out_y - bit_step_final)
        bit_curr_out_y = bit_curr_out_y - bit_step_final
      Endif
    Endif    
  Endif
  
  REM Z- Achse
  If(abs(meas_bit_z - volt2bit(FPAR_12)) > max_meas_diff_bit ) Then
    If (meas_bit_z < volt2bit(FPAR_12)) Then
      DAC(6, bit_curr_out_z + bit_step)
      bit_curr_out_z = bit_curr_out_z + bit_step
    Endif
    
    If (meas_bit_z > volt2bit(FPAR_12)) Then
      DAC(6, bit_curr_out_z - bit_step)
      bit_curr_out_z = bit_curr_out_z - bit_step
    Endif
    
  Else
    If(abs(meas_bit_z - volt2bit(FPAR_12)) > max_meas_diff_bit_final ) Then
      If (meas_bit_z < volt2bit(FPAR_12)) Then
        DAC(6, bit_curr_out_z + bit_step_final)
        bit_curr_out_z = bit_curr_out_z + bit_step_final
      Endif
    
      If (meas_bit_z > volt2bit(FPAR_12)) Then
        DAC(6, bit_curr_out_z - bit_step_final)
        bit_curr_out_z = bit_curr_out_z - bit_step_final
      Endif
    Endif    
  Endif
  
  

  
  
  FPar_15 = bit2volt(meas_bit_x)
  FPar_16 = bit2volt(meas_bit_y)
  FPar_17 = bit2volt(meas_bit_z)
  
  'CPU_Sleep((1/step_freq) * 100000000)
  
Finish:
