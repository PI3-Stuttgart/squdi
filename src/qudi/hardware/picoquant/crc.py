import csv

def _crc_ccitt_ffff(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc

def get_chck_summ(filename="waveform.csv"):
    f = open(filename)
    data = csv.reader(f, delimiter=';')
    amplitude = bytearray()
    for row in data:
        for column in row:
            amplitude.append(int(str(column),0))
            amplitude.append(0)
    f.close()
    return hex(_crc_ccitt_ffff(bytes(amplitude)))

def get_chck_summ_from_array(voltages):
    amplitude = bytearray()
    for v in voltages:
        amplitude.append(int(v))
        amplitude.append(0)
    return hex(_crc_ccitt_ffff(bytes(amplitude)))