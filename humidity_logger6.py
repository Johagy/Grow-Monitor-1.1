#source env/bin/activate
#pip3 install adafruit-circuitpython-dht
#python3 ~/dht22/humidity_logger6.py
import os
import time
import logging
import glob
import re
from typing import List, Dict, Optional
from dataclasses import dataclass
import signal
import sys
import adafruit_dht
import board
from datetime import datetime

# Konstanten
DATA_DIR = '/home/johagy/dht22'
MEASUREMENT_INTERVAL = 10  # Sekunden

# Logging Konfiguration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(DATA_DIR, 'humidity_logger.log')),
        logging.StreamHandler()
    ]
)

@dataclass
class SensorConfig:
    """Konfiguration für einen einzelnen DHT22 Sensor."""
    pin: board.pin
    name: str
    device: Optional[adafruit_dht.DHT22] = None

class HumidityLogger:
    """Klasse zum Loggen von Temperatur und Luftfeuchtigkeit von mehreren DHT22 Sensoren."""
    
    def __init__(self):
        # Sensor-Konfigurationen für alle 5 DHT22 Sensoren
        self.sensor_configs = [
            SensorConfig(board.D24, "Sensor1"),  # Spinnenfarm Eintritt
            SensorConfig(board.D18, "Sensor2"),  # Schwarzebox Eintritt
            SensorConfig(board.D23, "Sensor3"),  # Raum
            SensorConfig(board.D25, "Sensor4"),  # Spinnen Farmer Austritt
            SensorConfig(board.D12, "Sensor5")   # Schwarzebox Austritt
        ]
        self.csv_file = None
        self.current_date = None
        self.running = True
        
        # Signal Handler für sauberes Beenden
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        """Handler für sauberes Beenden des Programms."""
        if not self.running:  # Already shutting down
            return
        logging.info("Beende Programm...")
        self.running = False

    def get_csv_filename(self) -> str:
        """Generiert den Dateinamen für die aktuelle CSV-Datei."""
        current_date = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(DATA_DIR, f'humidity_{current_date}.csv')

    def initialize_sensors(self):
        """Initialisiert alle Sensoren."""
        for config in self.sensor_configs:
            try:
                config.device = adafruit_dht.DHT22(config.pin)
                logging.info(f"Sensor {config.name} erfolgreich initialisiert")
            except Exception as e:
                logging.error(f"Fehler bei der Initialisierung von {config.name}: {str(e)}")
                raise

    @staticmethod
    def load_csv_files(data_dir: str, prefix: str) -> List[str]:
        """
        Lädt alle CSV-Dateien aus dem angegebenen Verzeichnis, die mit dem prefix beginnen.
        
        Args:
            data_dir: Verzeichnis, in dem die CSV-Dateien gesucht werden
            prefix: Prefix der CSV-Dateien (z.B. 'humidity')
            
        Returns:
            Liste der gefundenen CSV-Dateien, sortiert nach Datum
        """
        if not os.path.exists(data_dir):
            logging.error(f"Verzeichnis nicht gefunden: {data_dir}")
            return []
            
        pattern = os.path.join(data_dir, f'{prefix}_*.csv')
        files = glob.glob(pattern)
        
        if not files:
            logging.warning(f"Keine Dateien gefunden die dem Muster entsprechen: {pattern}")
            return []
        
        def extract_date(filename):
            # Extrahiert das Datum aus dem Dateinamen (Format: humidity_YYYY-MM-DD.csv)
            match = re.search(r'_(\d{4}-\d{2}-\d{2})', filename)
            return match.group(1) if match else ''
            
        return sorted(files, key=extract_date)

    def initialize_csv(self):
        """Initialisiert die CSV-Datei für den aktuellen Tag."""
        try:
            filename = self.get_csv_filename()
            file_exists = os.path.exists(filename)
            
            if self.csv_file:
                self.csv_file.close()
                
            self.csv_file = open(filename, 'a')
            self.current_date = datetime.now().date()
            
            if not file_exists:
                # Schreibe Header wenn die Datei neu ist
                header = "Datum,Uhrzeit"
                for config in self.sensor_configs:
                    header += f",{config.name}_Temp,{config.name}_Hum"
                self.csv_file.write(header + "\n")
                
            logging.info(f"CSV-Datei initialisiert: {filename}")
            
        except Exception as e:
            logging.error(f"Fehler beim Initialisieren der CSV-Datei: {str(e)}")
            raise

    def check_and_rotate_file(self):
        """Prüft ob ein neuer Tag begonnen hat und rotiert ggf. die Datei."""
        current_date = datetime.now().date()
        if current_date != self.current_date:
            logging.info("Neuer Tag begonnen - rotiere Logdatei")
            self.initialize_csv()

    def read_sensor(self, sensor: adafruit_dht.DHT22) -> tuple[float, float]:
        """Liest Temperatur und Luftfeuchtigkeit von einem Sensor."""
        attempts = 5
        while attempts > 0:
            try:
                return sensor.temperature, sensor.humidity
            except RuntimeError as e:
                attempts -= 1
                if attempts == 0:
                    raise
                logging.warning(f"Fehler beim Sensor-Reading, verbleibende Versuche: {attempts}")
                time.sleep(3)

    def log_measurements(self):
        """Liest alle Sensoren aus und schreibt die Daten in die CSV-Datei."""
        try:
            self.check_and_rotate_file()
            
            measurements = []
            current_date = time.strftime('%d/%m/%y')
            current_time = time.strftime('%H:%M')
            
            for config in self.sensor_configs:
                if config.device:
                    try:
                        temp, hum = self.read_sensor(config.device)
                        measurements.extend([f"{temp:.1f}", f"{hum:.1f}"])
                    except Exception as e:
                        logging.error(f"Fehler beim Lesen von {config.name}: {str(e)}")
                        measurements.extend(["NA", "NA"])
                else:
                    measurements.extend(["NA", "NA"])
            
            log_line = f"{current_date},{current_time},{','.join(measurements)}\n"
            self.csv_file.write(log_line)
            self.csv_file.flush()
            logging.info("Messung erfolgreich aufgezeichnet")
            
        except Exception as e:
            logging.error(f"Fehler bei der Messung: {str(e)}")

    def cleanup(self):
        """Aufräumen beim Beenden."""
        try:
            if self.csv_file:
                self.csv_file.close()
            
            for config in self.sensor_configs:
                if config.device:
                    try:
                        config.device.exit()
                    except Exception as e:
                        logging.warning(f"Fehler beim Beenden von {config.name}: {str(e)}")
            
            logging.info("Cleanup abgeschlossen")
        except Exception as e:
            logging.error(f"Fehler während Cleanup: {str(e)}")

    def run(self):
        """Hauptschleife des Programms."""
        try:
            self.initialize_sensors()
            self.initialize_csv()
            
            logging.info("Starte Messungen...")
            while self.running:
                try:
                    self.log_measurements()
                    # Use shorter sleep intervals to allow more responsive shutdown
                    for _ in range(MEASUREMENT_INTERVAL):
                        if not self.running:
                            break
                        time.sleep(1)
                except Exception as e:
                    logging.error(f"Fehler bei der Messung: {str(e)}")
                    if not self.running:  # If we're shutting down, don't wait
                        break
                    time.sleep(5)  # Wait a bit before retrying if there was an error
                    
        except Exception as e:
            logging.error(f"Kritischer Fehler: {str(e)}")
        finally:
            self.cleanup()

if __name__ == '__main__':
    logger = HumidityLogger()
    logger.run()