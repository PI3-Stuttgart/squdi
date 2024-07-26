import hahn_echo_class


pi_half_len = 20
pi_len = 40
freq = 50e6
amp_corr = 1
t_min = 5
t_max = 50
dt = 4

hahnecho = hahn_echo_class.hahn_echo(pi_half_len, pi_len, freq, amp_corr, t_min, t_max, dt)

hahnecho.program()