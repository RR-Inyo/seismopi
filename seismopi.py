#!/usr/bin/env python3
# -*- coding: utf-8 -*
# seismopi.py
# Tests of: - Use of motion sensors MPU6050
# - Timer interval execution by signal handler, running in child process
# - Acquiring acceleration data received via I2C in signal handler in child process through queue
# - Serializing acceleration data by pickle - Continuously calculating shindo every 3 sec until going down below 2
# - Separating I2C buses for accelerometer and OLED display by Linux bitbang
# (c) 2021 @RR_Inyo
# Released under the MIT license
# https://opensource.org/licenses/mit-license.php

from multiprocessing import Process, Queue
import os
import sys
import time
import signal
import numpy as np
import pigpio
import mpu6050
import shindo
from oled.device import ssd1306
from oled.render import canvas
from PIL import ImageFont
import pickle

BUS_SENSOR  = 1         # I2C bus number for motion sensor
SDA_SENSOR  = 2         # I2C SDA pin for motion sensor
SCL_SENSOR  = 3         # I2C SCL pin for motion sensor
ADDR_SENSOR = 0x68      # I2C slave address for motion sensor

TIMER       = 0.01      # [s], interval to call handler
TTAIL       = 30        # [s], time to keep on recording after earthquake being weakened
TMAX        = 300       # [s], maximum time to record acceleration
TKEEP       = 9         # [s], time to keep OLED display after earthquake ends
ATHRESHOLD  = 15.0      # [gal], threshold to detect earthquake
STHRESHOLD  = 1.6       # Shindo to exit continuous calculation
NDATA       = 300       # Number of data points for single chunk

BUS_OLED    = 11        # I2C bus number for OLED display
SDA_OLED    = 23        # I2C SDA pin for OLED display
SCL_OLED    = 24        # I2C SCL pin for OLED display
ADDR_OLED   = 0x3c      # I2C slave address for OLED display

# Child process
def proc(q: Queue, sensor: mpu6050.MPU6050):

    # Signal handler, as nested function
    def handler(signum, frame):
        # Sense acceleration
        a = np.zeros(3)
        a = sensor.measureAccel(unit = 'gal')

        # Pass value of a to parent process via queue
        q.put(a)

    # Set signal handler to SIGALRM and attach interval timer to it
    signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, TIMER, TIMER)

    # Do nothing anymore
    while True:
       pass

# Handler for keyboard interrupt
def ctrl_c(signum, frame):
    print('\nKeyboard interrupt (CTRL+C) detected.')
    try:
        p.terminate()
        print('Child process terminated')
    except:
        pass
    pi.stop()
    print('pigpio released')
    print('Program finished')
    sys.exit()

# Main routine
if __name__ == '__main__':

    DEBUG = False

    # Set handler for keyboard interrupt
    signal.signal(signal.SIGINT, ctrl_c)

    # Get DLPF setting from command-line arguments
    argv = sys.argv
    argc = len(argv)
    if argc > 1:
        LOWPASS = int(argv[1])
    else:
        LOWPASS = 2

    # Show initial message on terminal
    print('=' * 64)
    print('Seismo Pi - A Raspberry Pi-based seismometer')
    print('(c) 2021 @RR_Inyo')
    print('=' * 64)

    # Initialize pigpio
    pi = pigpio.pi()

    #pi.set_mode(SDA_SENSOR, pigpio.INPUT)
    #pi.set_mode(SCL_SENSOR, pigpio.INPUT)
    #pi.set_pull_up_down(SDA_SENSOR, pigpio.PUD_UP)
    #pi.set_pull_up_down(SCL_SENSOR, pigpio.PUD_UP)

    #pi.set_mode(SDA_OLED, pigpio.INPUT)
    #pi.set_mode(SCL_OLED, pigpio.INPUT)
    #pi.set_pull_up_down(SDA_OLED, pigpio.PUD_UP)
    #pi.set_pull_up_down(SCL_OLED, pigpio.PUD_UP)

    # Get motion sensor handler
    print('Initializing and wakeup sensor...')
    sensor = mpu6050.MPU6050(pi = pi, bus = BUS_SENSOR, addr = ADDR_SENSOR)
    time.sleep(0.01)
    sensor.wakeup()
    time.sleep(0.01)

    # Set DLPF
    print(f'Setting DLPF_CFG = {LOWPASS} for sensor...')
    sensor.setDLPF(LOWPASS)

    # Caliberate
    print('Calibratint sensor...')
    sensor.calofs(gravity = 'free')

    # Set OLED display
    print('Initializing OLED display...')
    font = ImageFont.truetype('VeraMono', 14)
    font_small = ImageFont.truetype('VeraMono', 10)
    #font = ImageFont.truetype('DSEG14Modern-RegularItalic.ttf', 14)
    #font_small = ImageFont.truetype('DSEG14Modern-RegularItalic.ttf', 10)
    oled = ssd1306(port = BUS_OLED, address = ADDR_OLED)

    # ====== The main loop starts here ======
    while True:

        # Show message on terminal
        print('Waiting for earthquake to happen...')

        # Wait for earthquake
        a_wait = np.zeros(3)
        while True:
            # Measure acceleration
            a_wait[:] = sensor.measureAccel(unit = 'gal')
            a_wait_total = np.sqrt(np.sum(a_wait**2))

            # Exit while loop if acceleration exceeds threshold
            if a_wait_total > ATHRESHOLD:
                break

            # Show clock
            # Show message on OLED display
            with canvas(oled) as draw:
                kwargs = {'font': font, 'fill': 1}
                draw.text((0, 0), 'Seismo Pi', **kwargs)
                draw.text((0, 16), 'Waiting for', **kwargs)
                draw.text((0, 32), '  Earthquake...', **kwargs)
                now = time.localtime()
                nowc = time.strftime('%Y-%m-%d %H:%M:%S', now)
                kwargs = {'font': font_small, 'fill': 1}
                draw.text((0, 52), nowc, **kwargs)

            # Wait
            time.sleep(0.05)

        # ======= Earthquake detected ======

        # Start process to measure acceleration
        q = Queue()
        p = Process(target = proc, args = (q, sensor))
        p.start()

        # Prepare NumPy ndarray and other variables
        now = time.localtime()
        now_happened = time.strftime('%Y-%m-%d %H:%M:%S', now)
        NMAX = int(TMAX / TIMER)    # Maximum number of datapoints
        a = np.zeros((NMAX, 3))     # NumPy ndarray to store 3-D acceleration
        s_max = 0                   # Maximum JMA shindo
        s_old = 0                   # Old value of shindo
        i = 0                       # Number of shindo calculations
        weakened = False            # Flag of earthquake weakened
        t0 = time.time()            # Time to begin recording

        # Show message on terminal
        print('Earthquake detected!!')
        print('Acquiring data from sensor and calculating shindo...')

        # Show mesage on OLED display
        with canvas(oled) as draw:
            kwargs = {'font': font, 'fill': 1}
            draw.text((0, 0), 'Earthquake!!', **kwargs)
            draw.text((0, 16), 'Calculating...', **kwargs)
            now = time.localtime()
            nowc = time.strftime('%Y-%m-%d %H:%M:%S', now)
            kwargs = {'font': font_small, 'fill': 1}
            draw.text((0, 52), nowc, **kwargs)

        # ====== Loop for data acquisition and shindo calculation starts here ======
        while True:

            # Get acceleration data through queue, NDATA points
            for j in range(NDATA):
                a[NDATA * i + j,:] = q.get()

            # Calculate JMA shindo
            s = shindo.getShindo(a[NDATA * i: NDATA * (i + 1),:], TIMER)
            if s > s_max:
                s_max = s

            # Exit continuous shindo calculation loop when shaking becomes weak
            # and time from earthquake being weakened exceeds a predefined time,
            # or maximum time to record elapses
            t2 = time.time()

            if not weakened:
                t1 = t2
            else:
                pass

            if not weakened and s < STHRESHOLD:
                weakened = True
                t1 = time.time()
                print('Earthquake weakened')
            elif weakened and s > STHRESHOLD:
                weakened = False
                print('Earthquake strengthened again')

            if (weakened and t2 - t1 > TTAIL) or t2 - t0 > TMAX:
                break

            # Show shindo on terminal
            print(f'Time elapsed from earthqake occurrence: {t2 - t0:.1f} s')
            print(f'JMA shindo now: {s} (震度{shindo.getShindoName(s)})')
            print(f'JMA shindo max: {s_max} (震度{shindo.getShindoName(s_max)})')

            # Show shindo on OLED display
            with canvas(oled) as draw:
                kwargs = {'font': font, 'fill': 1}
                draw.text((0, 0), 'Earthquake!!', **kwargs)
                draw.text((0, 16), f'Shindo Now {s}', **kwargs)
                draw.text((0, 32), f'Shindo Max {s_max}', **kwargs)
                now = time.localtime()
                nowc = time.strftime('%Y-%m-%d %H:%M:%S', now)
                kwargs = {'font': font_small, 'fill': 1}
                draw.text((0, 52), nowc, **kwargs)

            # Increment counter to store data
            i += 1

            # Preserve old shindo
            s_old = s

        # ====== Loop for data acquisition and shindo calculation ends here ======

        # Terminate process to measure earthquake
        p.terminate()

        # Show final resuls on terminal
        a_max = np.max(np.abs(a), axis = 0)
        a_total_max = np.max(np.sqrt(np.sum(a**2, axis = 1)))
        print('Earthquake ended...')
        print(f'Happened at {now_happened}')
        print(f'Maxuimum JMA shindo: {s_max}')
        print(f'Duration {t2 - t0:.1f}')
        print(f'Maximum acceleration, X: {a_max[0]:.1f} gal')
        print(f'Maximum acceleration, Y: {a_max[1]:.1f} gal')
        print(f'Maximum acceleration, Z: {a_max[2]:.1f} gal')
        print(f'Maximum acceleration, Total: {a_total_max:.1f} gal')
        print('-' * 16)

        # Show final results on OLED
        with canvas(oled) as draw:
            kwargs = {'font': font, 'fill': 1}
            draw.text((0, 0), 'Earthquake ended.', **kwargs)
            draw.text((0, 16), f'Shindo Max {s_max}', **kwargs)
            draw.text((0, 32), f'Max {a_total_max:.1f} gal', **kwargs)
            draw.text((0, 48), f'Duration {t2 - t0:.0f} s', **kwargs)

        # Save acceleration as pickle
        with open(f'pickles/accel.pickle-{now_happened.replace(" ", "_")}', 'wb') as f:
            pickle.dump(a[0 : NDATA * i, :], f)

        # Keep display for seconds
        time.sleep(TKEEP)
