import ADwin
import numpy as np
import TimeTagger
from time import sleep
import matplotlib.pyplot as plt

def set_scanner_position(position):
    #TODO.
    """
    interface with qudi hardware file.
    :param position: xyz array or a vstack.
    :return:
    """
def switch_laser_on(channel_id):
    pass #TODO
def switch_laser_off(channel_id):
    pass #TODO

def confocal_sweep_1D(axis='x', startang=-5, endang=5, number_of_sweeps=1, collection_time=1, number_of_steps=1000, vol_2=0):
    #TODO remove TT

    '''
    do a one dimensional confocal sweep
    :param axis: axis on which the sweep is performed
    :param startang: starting angle of the galvo mirror
    :param endang: ending angle of the galvo mirror
    :param number_of_sweeps: number of sweeps
    :param collection_time: time of count_collection in ms for each voltage
    :param number_of_steps: number of voltage steps
    :param vol_2: voltage on output 2
    :return: data of count and voltage for each step (counts, voltage channel 1, voltage channel 2)
    '''

    tagger = TimeTagger.createTimeTagger()                          #define Tagger
    counter = TimeTagger.CountBetweenMarkers(tagger=tagger, click_channel=1, begin_channel=2, n_values=number_of_steps*number_of_sweeps)        #define counter
    time_tagger_time = (number_of_steps * 1.1*number_of_sweeps * collection_time) / 1000 + 2
    max_angle = 22.5                                                #maximum angle that is possible on galvo
    min_angle = -22.5                                               #minimum angle that is possible on galvo
    startvoltage = int(5*(-startang/min_angle * 3277) + 32768)      #get start voltage from startang (interger for Adwin)
    endvoltage = int(5*(endang/max_angle * 3277) + 32768)           #get end voltage from endang (interger for Adwin)
    voltage_2 = int(32768 + 3277 * vol_2)
    if axis == 'x':                                                 #depending on the axis, the output channel changes
        channel_1 = 1
        channel_2 = 2
    elif axis == 'y':
        channel_1 = 2
        channel_2 = 1
    else:
        print('no valid axis')
    adw = ADwin.ADwin(0x1, 1)                            #define Adwin
    BTL = adw.ADwindir + "adwin" + "11" + ".btl"         #get BTL of Adwin
    adw.Boot(BTL)                                        #boot Adwin system

    adw.Set_Par(1, startvoltage)                         #set the parameter PAR_i
    adw.Set_Par(2, endvoltage)
    adw.Set_Par(3, number_of_sweeps)
    adw.Set_Par(4, channel_1)
    adw.Set_Par(5, collection_time)
    adw.Set_Par(6, number_of_steps)
    adw.Set_Par(7, voltage_2)
    adw.Set_Par(8, channel_2)
    PROCESS = "sweeping_1D.TB1"                          #input the process
    adw.Load_Process(PROCESS)                            #load process
    adw.Start_Process(1)                                 #start process
    counter.start()                                      #start counter
    sleep(time_tagger_time)
    counter.stop()                                       #stop counter
    data = counter.getData()                             #get data
    count_map = np.zeros((number_of_steps - 1, 3))           #define count_map matrix
    for i in range(number_of_steps - 1):                     #get average for each position
        counts = np.average(data[i::number_of_steps])
        count_map[i][0] = counts                         #append average counts
        count_map[i][1] = 5*(-startang/min_angle + i * ((endang/max_angle + startang/min_angle)/number_of_steps))   #append voltage on channel 1 for each position
        count_map[i][2] = vol_2                          #append voltage on channel 2
    TimeTagger.freeTimeTagger(tagger)                    #free timetagger
    return count_map

def confocal_sweep_2D(startang_x=-5, endang_x=5, startang_y=-5, endang_y=5, number_of_sweeps=1, number_of_steps_x=100, collection_time=1, number_of_steps_y=100):
    '''
    execute a confocal_sweep in 2 D
    :param startang_x: starting angle on x axis
    :param endang_x: end angle on x axis
    :param startang_y: starting angle on y axis
    :param endang_y: end angle on y axis
    :param number_of_sweeps: number of total sweeps
    :param number_of_steps_x: number of steps on x axis
    :param collection_time: time of collection of counts
    :param number_of_steps_y: number of steps on y axis
    :return: count map
    '''
    tagger = TimeTagger.createTimeTagger()                                 #define TimeTagger
    counter = TimeTagger.CountBetweenMarkers(tagger=tagger, click_channel=2, begin_channel=1,
                                             n_values=number_of_steps_x * number_of_steps_y * number_of_sweeps)
    time_tagger_time = (number_of_steps_x * number_of_steps_y * number_of_sweeps * (collection_time + 0.2)) / 1000 + 3
                                                                           #define counter and counter run time
    max_angle = 22.5                                                       #max angle of galvo
    min_angle = -22.5                                                      #min angle of galvo
    startvoltage_x = int(5 * (-startang_x/min_angle * 3277) + 32768)       #startvoltage of x axis in adwin datatype
    endvoltage_x = int(5 * (endang_x/max_angle * 3277) + 32768)            #endvoltage of x axis in adwin datatype
    startvoltage_y = int(5 * (-startang_y / min_angle * 3277) + 32768)     #startvoltage of y axis in adwin datatype
    endvoltage_y = int(5 * (endang_y / max_angle * 3277) + 32768)          #endvoltage of y axis in adwin datatype
    adw = ADwin.ADwin(0x1, 1)                                              #define start and boot adwin system
    BTL = adw.ADwindir + "adwin" + "11" + ".btl"
    adw.Boot(BTL)

    adw.Set_Par(1, startvoltage_x)                                         #set parameter for adwin script
    adw.Set_Par(2, endvoltage_x)
    adw.Set_Par(3, startvoltage_y)
    adw.Set_Par(4, endvoltage_y)
    adw.Set_Par(5, number_of_sweeps)
    adw.Set_Par(6, collection_time)
    adw.Set_Par(7, number_of_steps_x)
    adw.Set_Par(8, number_of_steps_y)
    PROCESS = "sweeping_2D.TB1"                                            #load and start adwin process
    adw.Load_Process(PROCESS)
    adw.Start_Process(1)
    counter.start()                                                        #start TimeTagger
    sleep(time_tagger_time)                                                #let TimeTagger run
    counter.stop()                                                         #stop TimeTagger
    data = counter.getData()                                               #get data from counter
    count_map = np.zeros((number_of_steps_y, number_of_steps_x, 3))        #create empty numpy array
    for i in range(number_of_steps_y):
        for j in range(number_of_steps_x):
            count_map[i][j][0] = np.average(data[number_of_steps_x*i+j::number_of_steps_x*number_of_steps_y])                           #add average counts
            count_map[i][j][1] = 5*(-startang_x/min_angle + j * ((endang_x/max_angle + startang_x/min_angle)/number_of_steps_x))        #add voltage of x axis
            count_map[i][j][2] = 5*(-startang_y/min_angle + i * ((endang_y/max_angle + startang_y/min_angle)/number_of_steps_y))        #add voltage of y axis
    return count_map

if __name__ == '__main__':
    # data = confocal_sweep_2D(startang_x=-5, endang_y=5, number_of_sweeps=2, number_of_steps_x=10, number_of_steps_y=20, collection_time=1)
    data = confocal_sweep_1D(startang=-5, endang=5, number_of_sweeps=20, number_of_steps=200, vol_2=0,
                             collection_time=10)
    print(data)
