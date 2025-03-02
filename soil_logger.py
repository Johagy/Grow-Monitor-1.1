#source ~/soil_sensor_env/bin/activate
#pip3 install adafruit-circuitpython-seesaw
#python3 ~/soil_sensor_env/soil_logger.py
import time
import board
import busio
from adafruit_seesaw.seesaw import Seesaw
import csv
import os
from pathlib import Path
from datetime import datetime
import logging

# Enhanced logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/johagy/soil_logger.log'),
        logging.StreamHandler()
    ]
)

# Configuration
DATA_DIR = '/home/johagy/soil_data'  # Changed to absolute path
LOGGING_INTERVAL = 30
CSV_HEADERS = ['Date', 'Time', 'Moisture1', 'Temperature1', 'Moisture2', 'Temperature2']
SENSOR_ADDRESSES = [0x36, 0x37]

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)
logging.info(f"Data directory: {DATA_DIR}")

def get_current_csv_file():
    current_date = datetime.now().strftime('%Y-%m-%d')
    return os.path.join(DATA_DIR, f'soil_data_{current_date}.csv')

def initialize_csv(file_path):
    if not os.path.exists(file_path):
        with open(file_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(CSV_HEADERS)
        logging.info(f"Created new log file: {file_path}")

def initialize_i2c():
    try:
        i2c = board.I2C()
        logging.info("I2C initialized successfully")
        return i2c
    except Exception as e:
        logging.error(f"I2C initialization error: {e}")
        return None

def read_sensors(sensors):
    readings = []
    for i, sensor in enumerate(sensors, 1):
        try:
            moisture = sensor.moisture_read()
            temperature = sensor.get_temp()
            readings.extend([moisture, temperature])
            logging.info(f"Sensor {i}: Moisture: {moisture}, Temperature: {temperature:.1f}°C")
        except Exception as e:
            logging.error(f"Error reading sensor {i}: {e}")
            readings.extend([None, None])
    return readings

def main():
    logging.info("Starting soil moisture logger...")
    
    i2c = initialize_i2c()
    if not i2c:
        logging.error("Failed to initialize I2C. Check connections.")
        return

    sensors = []
    for addr in SENSOR_ADDRESSES:
        try:
            sensor = Seesaw(i2c, addr=addr)
            sensor.moisture_read()  # Test reading
            sensors.append(sensor)
            logging.info(f"Initialized sensor at {hex(addr)}")
        except Exception as e:
            logging.error(f"Failed to initialize sensor at {hex(addr)}: {e}")

    if not sensors:
        logging.error("No sensors initialized. Exiting.")
        return

    logging.info(f"Logging interval: {LOGGING_INTERVAL} seconds")
    
    while True:
        try:
            csv_file = get_current_csv_file()
            initialize_csv(csv_file)
            
            readings = read_sensors(sensors)
            if any(reading is not None for reading in readings):
                current_time = datetime.now()
                with open(csv_file, 'a', newline='') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow([
                        current_time.strftime('%d/%m/%y'),
                        current_time.strftime('%H:%M')
                    ] + readings)
            
            time.sleep(LOGGING_INTERVAL)
            
        except KeyboardInterrupt:
            logging.info("Logging stopped by user")
            break
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
