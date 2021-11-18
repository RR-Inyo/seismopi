# seismopi
Seismometer by Raspberry Pi

## Introduction
Turn your Raspberry Pi a seismometer by connecting a motion sensor!

The Python program, seismopi.py in this repository acquires acceleration data from the motion sensor and calculates the JMA instrumental seismic intensity.

## How it looks like
See photo below. A motion sensor, Invensense MPU6050, and an OLED display is connected to Raspberry Pi via the I2C bus.
![Raspberry Pi Seismometer prototype](DSC02809_2.JPG)

## Record example
Below is a record of real earthquake which happend at 3:08 am on November 8, 2021 in Japan. The calculated JMA seismic intensity was 2.8.
![Real earthquake record](real-earthquake.png)
