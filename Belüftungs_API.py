#python3 ~/Poti/Belüftungs_API.py

from flask import Flask, request, jsonify
import spidev
import time
from threading import Thread, Lock
import logging
import math
import pandas as pd
import numpy as np
import os
from datetime import datetime
import traceback

# Setup logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class PowerLogger:
    """
    Dedicated class for consistent power data logging.
    Logs fan speed data at regular intervals regardless of speed changes.
    """
    def __init__(self, fan_controller):
        self.fan_controller = fan_controller
        self.log_interval = 60  # Log every minute
        self.running = False
        self.log_thread = None
        self.lock = Lock()
        self.log_dir = '/home/johagy/ventilation_logs'
        
        # Create directory if it doesn't exist
        os.makedirs(self.log_dir, exist_ok=True)
        logger.info(f"PowerLogger initialized with log interval of {self.log_interval} seconds")
    
    def start(self):
        """Start the logging thread"""
        with self.lock:
            if not self.running:
                self.running = True
                self.log_thread = Thread(target=self._log_loop)
                self.log_thread.daemon = True
                self.log_thread.start()
                logger.info("Power logger started - logging every minute")
    
    def stop(self):
        """Stop the logging thread"""
        with self.lock:
            self.running = False
            if self.log_thread:
                self.log_thread.join(timeout=2)
                logger.info("Power logger stopped")
    
    def _log_loop(self):
        """Main logging loop - runs in a separate thread"""
        last_date = None
        current_log_file = None
        
        while self.running:
            try:
                # Get current values
                current_date = datetime.now().strftime('%Y-%m-%d')
                current_speed = self.fan_controller.get_speed()
                pot_value = int(255 * (1 - current_speed / 100))  # Calculate pot value
                
                # Check if we need a new file (date changed or first run)
                if current_date != last_date or current_log_file is None:
                    last_date = current_date
                    current_log_file = os.path.join(self.log_dir, f'potentiometer_power_{current_date}.csv')
                    
                    # Create file with header if it doesn't exist
                    if not os.path.exists(current_log_file):
                        with open(current_log_file, 'w') as f:
                            f.write('Timestamp,PowerPercentage,RawPotValue\n')
                        logger.info(f"Created new power log file: {current_log_file}")
                
                # Log the data
                with open(current_log_file, 'a') as f:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    f.write(f"{timestamp},{current_speed},{pot_value}\n")
                    f.flush()  # Ensure data is written immediately
                
                logger.debug(f"Logged power data: {timestamp}, {current_speed}%, {pot_value}")
                
            except Exception as e:
                logger.error(f"Error in power logging: {e}")
                logger.error(traceback.format_exc())
            
            # Sleep until next logging interval
            time.sleep(self.log_interval)

class FanController:
    """
    Controls the fan speed via a digital potentiometer connected to the SPI bus.
    Provides manual and automatic VPD-based control.
    """
    def __init__(self):
        try:
            # Initialize SPI
            self.spi = spidev.SpiDev()
            self.spi.open(0, 0)  # SPI0, CE0
            self.spi.max_speed_hz = 976000
            self.spi.mode = 0
            self.spi.bits_per_word = 8
            
            # Control state
            self.current_speed = 0  # 0-100 in percentage
            self.auto_mode = False
            self.target_vpd = 1.0
            self.vpd_tolerance = 0.2
            
            # Threading
            self._control_thread = None
            self._running = False
            self._lock = Lock()
            
            # Initialize potentiometer to maximum resistance (fan off)
            success = self._set_raw_value(255)  # Start with fan off
            if not success:
                raise Exception("Failed to initialize potentiometer")
                
            logger.info("Fan controller initialized successfully")
            
            # Initialize and start power logger
            self.power_logger = PowerLogger(self)
            self.power_logger.start()
            
        except Exception as e:
            logger.error(f"Failed to initialize fan controller: {e}")
            logger.error(traceback.format_exc())
            raise

    def _set_raw_value(self, value):
        """
        Set the raw potentiometer value (0-255)
        For MCP41010:
        Command byte: 
        - Bit 7-4: Command (0001 = Write to wiper)
        - Bit 3-0: Address (0000 = Potentiometer 0)
        Data byte: 8-bit value (0-255)
        """
        try:
            value = max(0, min(255, int(value)))
            with self._lock:
                # Command byte: 0x11 for write to wiper 0
                command_byte = 0x11
                data_byte = value
                
                logger.debug(f"Setting raw value: {value}")
                logger.debug(f"Command byte: 0x{command_byte:02x}, Data byte: 0x{data_byte:02x}")
                
                result = self.spi.xfer2([command_byte, data_byte])
                logger.debug(f"SPI write result: {result}")
                
                # Add a small delay to ensure the value is set
                time.sleep(0.001)
            return True
        except Exception as e:
            logger.error(f"Error setting raw value: {e}")
            logger.error(traceback.format_exc())
            return False

    def set_speed(self, speed_percent):
        """
        Set the fan speed as a percentage (25-90)
        25% = minimum allowed speed
        90% = maximum allowed speed
        """
        try:
            # Enforce speed limits
            speed_percent = max(25, min(90, float(speed_percent)))
            
            # Map speed percentage to potentiometer value (inverted)
            # 15% speed = ~217 (reduced max resistance)
            # 85% speed = ~38 (increased min resistance)
            pot_value = int(255 * (1 - speed_percent / 100))
            
            logger.info(f"Setting speed {speed_percent}% -> pot value {pot_value}")
            
            # Note: PowerLogger handles the logging now, no need to log here
            
            if not self._set_raw_value(pot_value):
                raise Exception("Failed to set potentiometer value")
            
            self.current_speed = speed_percent
            return speed_percent
            
        except Exception as e:
            logger.error(f"Error setting fan speed: {e}")
            logger.error(traceback.format_exc())
            raise

    def test_potentiometer(self):
        """Test the potentiometer with specific values"""
        try:
            print("\nTesting MCP41010 potentiometer control...")
    
            # Test sequence - adjusted for 15-95% limits
            test_values = [
                (15, 217),   # Min speed = 15%
                (35, 166),   # ~35% speed
                (50, 127),   # 50% speed
                (70, 76),    # ~70% speed
                (85, 38),    # Max speed = 85%
                (15, 217),   # Back to min speed
            ]
    
            for speed, expected_value in test_values:
                print(f"\nSetting speed to {speed}% (pot value: {expected_value})")
                self.set_speed(speed)
                time.sleep(2)  # Wait to observe effect
            
            print("\nTest complete")
            return True
        except Exception as e:
            print(f"Test failed: {e}")
            logger.error(f"Potentiometer test failed: {e}")
            logger.error(traceback.format_exc())
            return False
                
    def get_speed(self):
        """Get current fan speed as percentage"""
        return self.current_speed

    def set_auto_mode(self, enabled, target_vpd=None):
        """Enable/disable automatic VPD-based control"""
        self.auto_mode = enabled
        if target_vpd is not None:
            self.target_vpd = float(target_vpd)

        if enabled and not self._running:
            self._running = True
            self._control_thread = Thread(target=self._auto_control_loop)
            self._control_thread.daemon = True
            self._control_thread.start()
            logger.info(f"Auto mode enabled with target VPD: {self.target_vpd}")
        elif not enabled:
            self._running = False
            if self._control_thread:
                self._control_thread.join(timeout=2)
                self._control_thread = None
            logger.info("Auto mode disabled")

    def _auto_control_loop(self):
        """
        Automatic control loop based on VPD with time-based target adjustment
        and gradual speed changes
        """
        last_error = 0
        integral = 0
        
        # Reduced PID constants for smoother control
        kp = 0.5    # Proportional gain
        ki = 0.01    # Integral gain
        kd = 0.05    # Derivative gain
        
        # Rate limiting parameters
        max_speed_change = 5.0  # Maximum speed change per iteration (percentage points)
        
        while self._running:
            try:
                # Check current time for VPD target adjustment
                current_hour = datetime.now().hour
                current_minute = datetime.now().minute
                
                # Adjust target VPD based on time
                # Between 21:00 and 05:30, set target VPD to 1.0
                if (current_hour >= 21) or (current_hour < 5) or (current_hour == 5 and current_minute <= 30):
                    night_target_vpd = 1.0
                    if self.target_vpd != night_target_vpd:
                        logger.info(f"Night time period - adjusting target VPD to {night_target_vpd}")
                        self.target_vpd = night_target_vpd
                
                current_vpd = self._get_current_vpd()
                
                if current_vpd is None:
                    logger.warning("Could not get current VPD, skipping control iteration")
                    time.sleep(5)
                    continue

                # Calculate error
                error = current_vpd - self.target_vpd
                
                # Limit integral windup
                integral = max(-20, min(20, integral + error))
                
                # Calculate derivative
                derivative = error - last_error
                
                # PID control
                adjustment = -((kp * error) + (ki * integral) + (kd * derivative))
                
                # Rate limiting - cap the maximum speed change
                adjustment = max(-max_speed_change, min(max_speed_change, adjustment))
                
                # Calculate new speed with limits
                new_speed = max(25, min(90, self.current_speed + adjustment))
                
                # Apply speed change if significant enough but not too large
                if abs(new_speed - self.current_speed) > 0.5:
                    self.set_speed(new_speed)
                
                last_error = error
                
                logger.info(f"Auto control: Current VPD: {current_vpd:.2f}, Target VPD: {self.target_vpd}, "
                          f"Adjustment: {adjustment:.1f}%, Speed: {new_speed:.1f}%")
                
            except Exception as e:
                logger.error(f"Error in auto control loop: {e}")
                logger.error(traceback.format_exc())
                time.sleep(5)
                continue

            # Control interval for smoother operation
            time.sleep(90)  # Adjust every 1,5 minutes

    def calculate_vpd(self, temperature, relative_humidity):
        """Calculate VPD (Vapor Pressure Deficit) in kPa"""
        try:
            if temperature is None or relative_humidity is None:
                return None
                
            svp = 0.61078 * np.exp((17.27 * temperature) / (temperature + 237.3))
            vpd = svp * (1 - (relative_humidity / 100))
            return vpd
        except Exception as e:
            logger.error(f"Error calculating VPD: {e}")
            return None

    def _get_current_vpd(self):
        """Get current VPD from latest sensor readings, excluding Raum sensor"""
        try:
            # Get the current day's DHT file
            current_date = datetime.now().strftime('%Y-%m-%d')
            dht_file = os.path.join('/home/johagy/dht22', f'humidity_{current_date}.csv')
            
            if not os.path.exists(dht_file):
                logger.error(f"DHT file not found: {dht_file}")
                return None
                
            # Read the last line of the file
            try:
                df = pd.read_csv(dht_file)
                if df.empty:
                    logger.error("Empty DHT data file")
                    return None
            except Exception as e:
                logger.error(f"Error reading DHT file: {e}")
                return None
                
            # Get the latest row
            latest = df.iloc[-1]
            
            # Calculate VPD for sensors 1, 2, 4, and 5 (excluding sensor 3/Raum)
            vpds = []
            for sensor_id in [1, 2]:  # Spinnenfarm and Schwarzebox Eintritt Sensors only 
                temp_col = f'Sensor{sensor_id}_Temp'
                hum_col = f'Sensor{sensor_id}_Hum'
                
                if temp_col in latest and hum_col in latest:
                    temp = latest.get(temp_col)
                    hum = latest.get(hum_col)
                    
                    if pd.notna(temp) and pd.notna(hum):
                        vpd = self.calculate_vpd(temp, hum)
                        if vpd is not None:
                            vpds.append(vpd)
                else:
                    logger.warning(f"Missing columns for sensor {sensor_id} in DHT data")
            
            # Calculate average VPD if we have at least one valid reading
            if vpds:
                avg_vpd = sum(vpds) / len(vpds)
                logger.info(f"Current average VPD: {avg_vpd:.2f} kPa from {len(vpds)} sensors")
                return avg_vpd
            else:
                logger.error("No valid VPD readings available")
                return None
                
        except Exception as e:
            logger.error(f"Error getting current VPD: {e}")
            logger.error(traceback.format_exc())
            return None

    def cleanup(self):
        """Cleanup resources"""
        try:
            self.set_auto_mode(False)  # Stop control thread
            self.power_logger.stop()   # Stop the power logger
            self.spi.close()
            logger.info("Fan controller cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

# Initialize controller
fan_controller = FanController()

# API endpoints
def register_ventilation_endpoints(app):
    @app.route('/api/ventilation/speed', methods=['GET', 'POST'])
    def ventilation_speed():
        """Endpoint to get or set the fan speed"""
        if request.method == 'POST':
            try:
                data = request.get_json()
                if data is None:
                    return jsonify({'error': 'No JSON data received'}), 400
                
                speed = float(data.get('speed', 0))
                actual_speed = fan_controller.set_speed(speed)
                return jsonify({'speed': actual_speed})
                
            except ValueError as e:
                logger.error(f"Invalid speed value: {e}")
                return jsonify({'error': 'Invalid speed value'}), 400
            except Exception as e:
                logger.error(f"Error setting speed: {e}")
                logger.error(traceback.format_exc())
                return jsonify({'error': str(e)}), 500
                
        # GET request
        try:
            return jsonify({'speed': fan_controller.get_speed()})
        except Exception as e:
            logger.error(f"Error getting speed: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'error': str(e)}), 500

    @app.route('/api/ventilation/auto', methods=['GET', 'POST'])
    def ventilation_auto():
        """Endpoint to get or set the automatic mode"""
        if request.method == 'POST':
            try:
                data = request.get_json()
                if data is None:
                    return jsonify({'error': 'No JSON data received'}), 400
                
                enabled = data.get('enabled', False)
                target_vpd = data.get('target_vpd')
                
                if target_vpd is not None:
                    try:
                        target_vpd = float(target_vpd)
                    except ValueError:
                        return jsonify({'error': 'Invalid target VPD value'}), 400
                
                fan_controller.set_auto_mode(enabled, target_vpd)
                
                return jsonify({
                    'auto_mode': fan_controller.auto_mode,
                    'target_vpd': fan_controller.target_vpd,
                    'current_speed': fan_controller.current_speed
                })
                
            except Exception as e:
                logger.error(f"Error setting auto mode: {e}")
                logger.error(traceback.format_exc())
                return jsonify({'error': str(e)}), 500
                
        # GET request
        try:
            return jsonify({
                'auto_mode': fan_controller.auto_mode,
                'target_vpd': fan_controller.target_vpd,
                'current_speed': fan_controller.current_speed
            })
        except Exception as e:
            logger.error(f"Error getting auto mode status: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'error': str(e)}), 500

    @app.route('/api/ventilation/status', methods=['GET'])
    def ventilation_status():
        """Endpoint to get comprehensive ventilation system status"""
        try:
            # Get current VPD
            current_vpd = fan_controller._get_current_vpd()
            
            # Get current day's log file for counts
            current_date = datetime.now().strftime('%Y-%m-%d')
            log_file = os.path.join('/home/johagy/ventilation_logs', f'potentiometer_power_{current_date}.csv')
            log_count = 0
            last_log_time = None
            
            if os.path.exists(log_file):
                try:
                    df = pd.read_csv(log_file)
                    log_count = len(df)
                    if not df.empty and 'Timestamp' in df.columns:
                        last_log_time = df['Timestamp'].iloc[-1]
                except Exception as e:
                    logger.error(f"Error reading log file for status: {e}")
            
            return jsonify({
                'current_speed': fan_controller.current_speed,
                'auto_mode': fan_controller.auto_mode,
                'target_vpd': fan_controller.target_vpd,
                'current_vpd': current_vpd,
                'log_file': log_file,
                'log_count': log_count,
                'last_log_time': last_log_time,
                'system_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
        except Exception as e:
            logger.error(f"Error getting ventilation status: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    try:
        app = Flask(__name__)
        register_ventilation_endpoints(app)
        
        # Run test before starting server
        if fan_controller.test_potentiometer():
            logger.info("MCP41010 potentiometer test passed")
        else:
            logger.error("MCP41010 potentiometer test failed")
            
        logger.info("Starting ventilation control API on port 5001")
        app.run(host='0.0.0.0', port=5001)
    except Exception as e:
        logger.error(f"Failed to start ventilation control API: {e}")
        logger.error(traceback.format_exc())
    finally:
        # Make sure to clean up resources when the server exits
        try:
            fan_controller.cleanup()
        except:
            pass
