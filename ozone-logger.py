#!/usr/bin/python3
#
# Bill Simpson (wrsimpson@alaska.edu) 3 Sep 2019
#
# This logger captures data from a Dasibi 1008 RS using a Raspberry Pi
# It uses a hardware UART serial port (/dev/serial0) on the RPi, which has
# 0 and 3.3V logic levels and a hardware converter from those levels to
# RS-232 logic levels (+/- 9V) to talk with the Dasibi serial output
# It also uses a Pimoroni Explorer PHat to log the output as an analog
# voltage.  The explorer phat has digital outputs that span and zero
# the Dasibi, but that also required hardware to convert the digital output
# to +5V signals.

import serial
import time
import datetime

# control variables
write_interval_secs = 50 # will write a data line about this often
# even if serial port fails to report digital data

cal_start_hour = 12 # cal starts at hour:00 in the native timezone
cal_span_secs = 300 # seconds to span
cal_zero_secs = 300 # seconds to zero (after span)
# be careful to not calibrate across midnight

time_exception_secs = 100 # if time shifts more than this, there will
# be a time exception and a new file will begin

# set time format for datetime string in file
timeformat = '%Y-%m-%d %H:%M:%S'

# specifics for analog read, calmode, and time
basevarnames = ['datetime', 'calmode', 'O3_volts']

# specifics for reading serial port
varnames = ['O3_ppb','fault','mode','abscoef','offset_ppb','temp_c','pres_atm','cont_hz','samp_hz']
position = ['05;17H','07;12H','07;25H','07;38H','07;56H','08;11H','09;11H','10;11H','10;32H']
unit = ['ppm', '', '', '', '', 'C', 'ATM', '', '']

try:
    ser = serial.Serial(port='/dev/serial0')
    ser.baudrate=9600
    ser.timeout=20  # using 20 second timeout
    ser.bytesize=7  # note that the O3 instrument uses 7 data bits!
    ser.parity='N'
    ser.stopbits=1
    ser.flush()
    time.sleep(5)  # wait 5 seconds to let analyzer stabilize
    ser.write('d'.encode())

except:
    print('Cannot open serial port')
    exit(1)

try:
    import explorerhat
    O3_volts = explorerhat.analog.one
    zero = explorerhat.output.one
    span = explorerhat.output.two
except:
    print('Failed to open explorerhat')

# create full header for file
headernames = basevarnames + varnames

# set last write monotonic time to now
lastwrite_monotonic = time.monotonic()

# indicate outfile is not open
outfile_open = False

while True:
    walltime = datetime.datetime.now()

    # calculate the start and end times for calibration on today
    # calspan = time to start spanning
    calspan = walltime.replace(hour=cal_start_hour,minute=0,second=0,
                               microsecond=0)
    # time to start zero
    calzero = calspan + datetime.timedelta(seconds=cal_span_secs)
    # time to end calibration
    calend = calzero + datetime.timedelta(seconds=cal_zero_secs)
    request_calmode = 0
    if walltime > calspan and walltime < calzero:
        request_calmode = 3
    if walltime > calzero and walltime < calend:
        request_calmode = 1
    if request_calmode & 2:
        span.on()
    else:
        span.off()
    if request_calmode & 1:
        zero.on()
    else:
        zero.off()

    # now read serial data
    datline = ser.readline().decode()
    serialvector = []

    for ix, loc in enumerate(position):
        try:
            strloc = datline.find('\x1b['+loc+'\x00')
            if strloc > -1:
                dataval = datline[(strloc+9):].strip().split('\x1b[')[0]
                if dataval.find(unit[ix]) > -1:
                    serialvector.append(dataval.split(' ')[0])
        except:
            pass

    # read the serial's ozone and convert to ppb
    try:
        serialvector[0] = str(1000*float(serialvector[0]))
    except:
        if len(serialvector)>0:
            serialvector[0] = 'NaN'
    # check if there are the right number of elements in the serial vector
    valid_serial_data = (len(serialvector) == 9)

    secs_since_write = time.monotonic() - lastwrite_monotonic
#    print('secs_since_write ='+str(secs_since_write))
    if valid_serial_data or ( secs_since_write > write_interval_secs ) :
        # write some new data
        if not outfile_open:
            outfilename = datetime.datetime.now().strftime('ozone-log-%Y%m%dT%H%M%S.txt')
            outfile = open(outfilename,'w')
            # write the header line
            outfile.write('\t'.join(headernames)+'\n')
            outfile_open = True
            # set last datetime to now
            last_dt = datetime.datetime.now()
            secs_since_write = 0
        # write the data line
        pred_dt = last_dt + datetime.timedelta(seconds=secs_since_write)
        if not valid_serial_data:
            serialvector = ['NaN'] * 9  # fill values with NaNs
            # try to get the serial port into diagnostic mode
            ser.write('d'.encode())
        # build the base data
        basedata = []
        basedata.append(pred_dt.strftime(timeformat))
        # calculate actual calmode
        calmode = int(span.is_on()) << 1 | int(zero.is_on())
        # add to base data vector
        basedata.append(str(calmode))
        basedata.append(str(O3_volts.read()))
        # concatenate to total vector of base + serial vector
        totalvector = basedata + serialvector
        # write totaldata vector
        outfile.write('\t'.join(totalvector)+'\n')
        # output to console in case anybody is there
        print('\t'.join(totalvector))
        # check if time shifted by more than allowed
        curr_dt = datetime.datetime.now()
        diff_secs = (curr_dt - pred_dt).total_seconds()

        if abs(diff_secs) > time_exception_secs:
            exception_string = 'Time shift exception -- computer time is: '
            exception_string += curr_dt.strftime(timeformat)
            exception_string += ' predicted time was: '
            exception_string += pred_dt.strftime(timeformat)
            exception_string += ' seconds time shifted = '
            exception_string += str(diff_secs)+'\n'
            outfile.write(exception_string)
            outfile.close()
            outfile_open = False
        else:
            # if date changes, close the old file and let a new one open
            if last_dt.date() < curr_dt.date():
                outfile.close()
                outfile_open = False

        # set last_dt from current write time
        last_dt = curr_dt
        # set the lastwrite seconds to now
        lastwrite_monotonic = time.monotonic() 

