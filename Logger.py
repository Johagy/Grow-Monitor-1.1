#sudo apt install -y python3-picamera2 python3-libcamera
#python3 ~/camera_timelaps/Logger.py
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Comprehensive import handling
try:
    from picamera2 import Picamera2
    import libcamera
except ImportError as e:
    print(f"Critical Error: {e}")
    print("Please install required packages:")
    print("sudo apt install python3-picamera2 python3-libcamera")
    sys.exit(1)

class TimelapseCamera:
    def __init__(self, base_dir=None, camera_ports=None):
        """
        Initialize timelapse camera system
        :param base_dir: Base directory for storing images (default: ~/timelapse)
        :param camera_ports: List of camera ports to use (default: [0, 1])
        """
        # Default to home directory timelapse folder
        if base_dir is None:
            base_dir = str(Path.home() / "timelapse")
        
        # Default camera ports
        if camera_ports is None:
            camera_ports = [0, 1]
        
        # Setup logging
        self.setup_logging()
        
        # Create base directory
        self.base_dir = Path(base_dir)
        self.create_base_directory()
        
        # Camera configuration
        self.camera_ports = camera_ports
        
        # Initialize cameras
        self.cameras = self.initialize_cameras()
        logging.info(f"Successfully initialized {len(self.cameras)} cameras")

    def create_base_directory(self):
        """Create base directory for storing timelapse images"""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            logging.info(f"Created/verified base directory at {self.base_dir}")
        except PermissionError as e:
            logging.error(f"Permission denied creating directory {self.base_dir}. Error: {e}")
            raise
        except Exception as e:
            logging.error(f"Error creating directory {self.base_dir}. Error: {e}")
            raise

    def setup_logging(self):
        """Configure logging to console and file"""
        log_dir = Path.home() / "timelapse_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "timelapse.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(str(log_file), encoding='utf-8')
            ]
        )

    def initialize_cameras(self):
        """
        Initialize Raspberry Pi Camera Modules
        Attempts to open cameras on specified ports
        """
        cameras = {}
        for port in self.camera_ports:
            try:
                # Create Picamera2 instance
                picam2 = Picamera2(camera_num=port)
                
                # Configure camera for still capture
                config = picam2.create_still_configuration(
                    main={
                        "size": (2592, 1944),  # Higher resolution for wider angle
                        "format": "RGB888"
                    },
                    raw={"format": "SRGGB10_CSI2P"}  # Raw Bayer format
                )
                
                # Configure camera
                picam2.configure(config)
                
                # Add to cameras dictionary
                cameras[port] = picam2
                logging.info(f"Successfully initialized camera on port {port}")
            
            except Exception as e:
                logging.error(f"Error initializing camera on port {port}: {e}")
        
        return cameras

    def create_daily_folder(self):
        """Create folder for today's images"""
        today = datetime.now().strftime('%Y-%m-%d')
        daily_dir = self.base_dir / today
        try:
            daily_dir.mkdir(exist_ok=True)
            return daily_dir
        except Exception as e:
            logging.error(f"Error creating daily directory {daily_dir}: {e}")
            raise

    def get_camera_settings(self, port):
        """
        Get camera-specific settings with focus on reducing exposure for camera 1
        Camera 0 uses original settings, Camera 1 uses minimal exposure that prevents flickering
        """
        # Base settings for all cameras
        settings = {
            "FrameDurationLimits": (33333, 100000)  # Limit frame duration (in μs) to reduce flickering
        }
        
        # Camera 0 specific settings (first camera) - ORIGINAL SETTINGS RESTORED
        if port == 0:
            settings.update({
                "ExposureTime": 2000,        # Original exposure time
                "AnalogueGain": -1.5,        # Original gain value
                "AeEnable": False,           # Disable auto exposure as in original
                "AfMode": 0,                 # Manual focus mode
                "LensPosition": 0.7,         # Focus point (between 0-1)
            })
        
        # Camera 1 specific settings (second camera)
        # Focus on minimal exposure time while preventing flicker
        elif port == 1:
            settings.update({
                "ExposureTime": 7000,        # Reduced exposure time but still enough to prevent flicker
                "AnalogueGain": -0.9,         # Minimal gain to prevent overexposure
                "AeEnable": False,           # Disable auto exposure
                "AwbEnable": True,           # Enable auto white balance to handle colors automatically
                "LensPosition": 0.4,         # Focus point (between 0-1)                
                # Anti-flicker settings
                "AeFlickerPeriod": 10000,    # 10ms period for flicker reduction
                "AeFlickerMode": 1,          # Enable anti-flicker
                "Brightness": -0.1,          # Slight brightness reduction
                "Contrast": 1.0,             # Normal contrast
                "Saturation": 1.0            # Normal saturation
            })
        
        return settings

    def capture_images(self):
        """Capture images with minimal exposure settings for Camera 1"""
        if not self.cameras:
            logging.warning("No cameras available for capture")
            return

        try:
            daily_dir = self.create_daily_folder()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            for port, camera in self.cameras.items():
                try:
                    # Start camera 
                    camera.start()
                    
                    # Allow camera to stabilize
                    time.sleep(2)
                    
                    # Apply port-specific settings
                    camera_settings = self.get_camera_settings(port)
                    camera.set_controls(camera_settings)
                    
                    # Log settings for camera 1
                    if port == 1:
                        try:
                            current_settings = camera.capture_metadata()
                            logging.info(f"Camera 1 settings: ExposureTime={current_settings.get('ExposureTime')}, " +
                                        f"AnalogueGain={current_settings.get('AnalogueGain')}")
                        except:
                            pass
                    
                    # Allow settings to take effect
                    time.sleep(1.5)
                    
                    # Capture image
                    filename = f"camera_port_{port}_{timestamp}.jpg"
                    filepath = daily_dir / filename
                    camera.capture_file(str(filepath))
                    logging.info(f"Captured image from camera on port {port}: {filename}")
                        
                    # Stop camera
                    camera.stop()
                    
                except Exception as e:
                    logging.error(f"Error capturing image from camera on port {port}: {e}")
                    try:
                        camera.stop()
                    except:
                        pass
                    continue
            
        except Exception as e:
            logging.error(f"Comprehensive capture error: {e}")

    def run(self, interval_minutes=10):
        """
        Run continuous timelapse capture
        :param interval_minutes: Time between captures (default: 10 minutes)
        """
        logging.info(f"Starting timelapse capture every {interval_minutes} minutes")
        
        try:
            while True:
                self.capture_images()
                # Wait for next capture interval
                time.sleep(interval_minutes * 60)
        
        except KeyboardInterrupt:
            logging.info("Timelapse capture stopped by user")
        
        finally:
            self.cleanup()

    def cleanup(self):
        """Release all camera resources"""
        for port, camera in self.cameras.items():
            try:
                camera.stop()
                camera.close()
                logging.info(f"Released camera on port {port}")
            except Exception as e:
                logging.error(f"Error closing camera on port {port}: {e}")

def main():
    try:
        # Create and run timelapse camera
        timelapse = TimelapseCamera()
        
        # Check if any cameras were initialized
        if timelapse.cameras:
            timelapse.run(interval_minutes=3)  # Changed from default 10 to 3 minutes
        else:
            logging.error("No cameras were initialized. Please check connections and permissions.")
    
    except Exception as e:
        logging.error(f"Fatal error during timelapse setup: {e}")

if __name__ == "__main__":
    main()
