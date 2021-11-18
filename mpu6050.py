# mpu6050.py
# My implementation of class to use MPU6059 motion sensor
# Depends pigpio library
# (c) 2021 @RR_Inyo
# Released under the MIT license
# https://opensource.org/licenses/mit-license.php

import pigpio
import time
import struct
from typing import Tuple

class MPU6050:

    DEBUG = False

    # Contants to control MPU6050, I2C
    # Caution! Change 0x68 to 0x69 if AD0 pin is connected to VDD!
    I2C_ADDR        = 0x68
    I2C_BUS         = 1

    # Constants to control MPU6050, register map
    # Control to some of them are not implemted yet!
    # Only minimum required registers have been named for tests (2021-11-04)
    CONFIG          = 0x1A
    SMPLRT_DIV      = 0x19
    ACCEL_CONFIG    = 0x1C

    ACCEL_XOUT_H    = 0x3B
    ACCEL_XOUT_L    = 0x3C
    ACCEL_YOUT_H    = 0x3D
    ACCEL_YOUT_L    = 0x3E
    ACCEL_ZOUT_H    = 0x3F
    ACCEL_ZOUT_L    = 0x40
    PWR_MGMT_1      = 0x6B

    # Constants to calculate and calibrate acceleration
    RES             = 1 / 16384 # [g], LSB
    G2GAL           = 980.665   # [gal/g]
    G2MPSSQ         = 9.80665   # [m/s**2/g]
    N_CAL           = 50        # Times to get calibration data
    T_CAL           = 0.005     # Interval to get calibration data

    # Constructor
    def __init__(self, pi: pigpio.pi, bus: int = I2C_BUS, addr: int = I2C_ADDR) -> None:
        # Open I2C bus and get handle
        self._pi = pi
        self._h = self._pi.i2c_open(bus, addr)
        if self._h < 0:
            raise Exception('Can\'t open I2C bus by pigpio library')

        # Set default settings to various registers
        # - Set measuring mode
        # - Set full resolution mode
        # - set range +/-2 g

        # Initialize digital low-pass filter setting
        self.DLPF_CFG = 0

        # Initialize offsets
        self._ofsx = 0
        self._ofsy = 0
        self._ofsz = 0

    # Destructor
    def __del__(self) -> None:
        pass

    # Wake up, reset SLEEP bit in PWR_MGMT_1 register
    def wakeup(self) -> None:
        # Read, modify only bit 6, write back
        d = self._pi.i2c_read_byte_data(self._h, MPU6050.PWR_MGMT_1)
        d &= 0b101111
        self._pi.i2c_write_byte_data(self._h, MPU6050.PWR_MGMT_1, d)

    # Set digital low-pass filter
    def setDLPF(self, cfg: int) -> None:
        if 0 <= cfg <= 6:
            self.DLPF_CFG = cfg
            # Read, modify only bits 2-0, write back
            d = self._pi.i2c_read_byte_data(self._h, MPU6050.CONFIG)
            d &= 0b11111000
            d |= self.DLPF_CFG
            self._pi.i2c_write_byte_data(self._h, MPU6050.CONFIG, d)
        else:
            raise ValueError('Invalid digital LPF setting (DLPG_CFG) value')

    # Measure acceleration
    def measureAccel(self, unit: str = 'g') -> Tuple[float, float, float]:
        # Read from DATAX0 to DATAZ1
        (b, d) = self._pi.i2c_read_i2c_block_data(self._h, MPU6050.ACCEL_XOUT_H, 6)

        if MPU6050.DEBUG:
            print(f'Bytes read: {b}')
            print(f'Raw data: {d}')

        # Unpack data
        if b > 0:
            (x_raw, y_raw, z_raw) = struct.unpack('>3h', d)
        else:
            raise Exception(f'Data acquisition from device on I2C bus {MPU6050.I2C_BUS}, address {MPU6050.I2C_ADDR:#02x} failed')
            (x_raw, y_raw, z_raw) = (0, 0, 0)

        # Subtract software offsets
        x_raw -= self._ofsx
        y_raw -= self._ofsy
        z_raw -= self._ofsz

        # Calculate and return acceleration in specified unit and return
        if unit == 'g':
            coeff = MPU6050.RES
        elif unit == 'gal':
            coeff = MPU6050.RES * MPU6050.G2GAL
        elif unit == 'm/s**2':
            coeff = MPU6050.RES * MPU6050.G2MPSSQ
        elif unit == 'raw':
            coeff = 1.0
        else:
            raise ValueError('No such unit supported')

        return (x_raw * coeff, y_raw * coeff, z_raw * coeff)

    # Clear offset setting values
    def clearofs(self) -> None:
        self._ofsx = 0
        self._ofsy = 0
        self._ofsz = 0

    # Perform offset calibration, by software
    def calofs(self, gravity: str = 'z+') -> None:
        # Clear offset registers
        self.clearofs()

        # Measure T_CAL times and take average
        x_ave = 0
        y_ave = 0
        z_ave = 0
        for _ in range(MPU6050.N_CAL):
            (x, y, z) = self.measureAccel(unit = 'raw')
            x_ave += x
            y_ave += y
            z_ave += z
            time.sleep(MPU6050.T_CAL)
        x_ave /= MPU6050.N_CAL
        y_ave /= MPU6050.N_CAL
        z_ave /= MPU6050.N_CAL

        if MPU6050.DEBUG:
            print('Averages:')
            print(f'X: {x_ave}, Y: {y_ave}, Z: {z_ave}')

        # Gravity
        one_g = int(1.0 / MPU6050.RES)

        self._ofsx = int(x_ave)
        self._ofsy = int(y_ave)
        self._ofsz = int(z_ave)

        # Add or subtract 1 g to offset
        if gravity == 'x+':
            self._ofsx -= one_g
        elif gravity == 'x-':
            self._ofsx += one_g
        if gravity == 'y+':
            self._ofsy -= one_g
        elif gravity == 'y-':
            self._ofsy += one_g
        elif gravity == 'z+':
            self._ofsz -= one_g
        elif gravity == 'z-':
            self._ofsz += one_g
        elif gravity == 'free':
            pass
        else:
            raise ValueError('Invalid calibration vertical option')

# Test bench
if __name__ == '__main__':

    # Get pigpio handler
    pi = pigpio.pi()

    # Get MPU6050 handler, passing pigpio handler
    sensor = MPU6050(pi)

    # Wake up MPU6050
    sensor.wakeup()

    # Perform calibration by software, z-axis being vertical
    sensor.calofs(gravity = 'z+')

    # Read after calibration
    print('After offset calibration:')
    (x, y, z) = sensor.measureAccel()
    print(f'X: {x:.4f}, Y: {y:.4f}, Z: {z:.4f}, [g]')

    # Measure acceleration in various units
    print('Perform measurement every 0,1 s')
    for unit in ['g', 'gal', 'm/s**2']:
        t0 = time.time()
        while True:
            # Perform measurement
            (x, y, z) = sensor.measureAccel(unit = unit)

            # Show it on terminal
            print(f'X: {x:.4f}, Y: {y:.4f}, Z: {z:.4f}, [{unit}]')

            # Sleep
            time.sleep(0.1)

            # Exit if 10 sec passes
            t1 = time.time()
            if t1 - t0 > 10:
                break

    print('Test done.')
    pi.stop()
