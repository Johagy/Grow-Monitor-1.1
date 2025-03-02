#source ~/growmonitor-env/bin/activate
#pip install dash dash-daq requests apscheduler RPi.GPIO
#pip install pandas dash plotly dash-core-components dash-html-components dash-table requests
#python3 ~/UI/GeneralUI3.py
import dash
from dash import dcc, html
import dash_daq as daq
import base64
from pathlib import Path
import re
from dash.dependencies import Input, Output, State
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import glob
import os
import numpy as np
import requests
from dash import callback_context
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import traceback
import json

# Constants
DHT22_DATA_DIR = '/home/johagy/dht22'
SOIL_DATA_DIR = '/home/johagy/soil_data'

# Sensor Names Mapping
SENSOR_NAMES = {
    1: "Spinnenfarm Eintritt",
    2: "Schwarzebox Eintritt",
    3: "Raum",
    4: "Spinnen Farmer Austritt",
    5: "Schwarzebox Austritt",
    'soil1': "Spinnenfarm Boden",
    'soil2': "Schwarzebox Boden"
}

# Initialize Dash App with meta tags for responsive design
app = dash.Dash(__name__, meta_tags=[
    {"name": "viewport", "content": "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"},
    {"http-equiv": "X-UA-Compatible", "content": "IE=edge"},
    {"name": "theme-color", "content": "#1a1a1a"}
])

scheduler = BackgroundScheduler()
scheduler.start()

# Helper Functions
def get_current_day_file(data_dir, prefix):
    """Get the file path for the current day with improved logging and better detection."""
    current_date = datetime.now().strftime('%Y-%m-%d')
    filename = f"{prefix}_{current_date}.csv"
    file_path = os.path.join(data_dir, filename)
    print(f"Looking for current day file: {file_path}")
    
    # First check if file exists
    if os.path.exists(file_path):
        print(f"Found current day file: {file_path}")
        try:
            # Verify file is readable and not empty
            with open(file_path, 'r') as f:
                first_line = f.readline()
                if first_line:
                    return file_path
                else:
                    print(f"Warning: Current day file is empty")
                    return _ensure_current_day_file(data_dir, prefix)
        except Exception as e:
            print(f"Error reading current day file: {str(e)}")
    
    # File doesn't exist, try to create it
    return _ensure_current_day_file(data_dir, prefix)
    
    # If file doesn't exist, try to create it for potentiometer power
    if prefix == 'potentiometer_power':
        power_dir = '/home/johagy/ventilation_logs'
        power_file = os.path.join(power_dir, f'potentiometer_power_{current_date}.csv')
        
        if not os.path.exists(power_file):
            try:
                # Create directory if it doesn't exist
                os.makedirs(power_dir, exist_ok=True)
                
                # Create empty power file with header
                with open(power_file, 'w') as f:
                    f.write("Timestamp,PowerPercentage,RawPotValue\n")
                print(f"Created empty power file with header: {power_file}")
                return power_file
            except Exception as e:
                print(f"Error creating power file: {str(e)}")
    
    print(f"Current day file not found or could not be created")
    return None
    
def load_ventilation_power_data(selected_date=None):
    """Load potentiometer power data from CSV files with improved error handling and file creation"""
    try:
        # If no date provided, use current date
        if selected_date is None:
            selected_date = datetime.now().strftime('%Y-%m-%d')
        elif isinstance(selected_date, str) and '/' in selected_date:
            # Extract date from full path if provided
            selected_date = selected_date.split('/')[-1].replace('potentiometer_power_', '').replace('.csv', '')
        
        # Construct file path
        log_dir = '/home/johagy/ventilation_logs'
        file_path = os.path.join(log_dir, f'potentiometer_power_{selected_date}.csv')
        
        print(f"Attempting to load power data from: {file_path}")
        
        # Create file if it doesn't exist (only for current day)
        if not os.path.exists(file_path) and selected_date == datetime.now().strftime('%Y-%m-%d'):
            try:
                # Create directory if it doesn't exist
                os.makedirs(log_dir, exist_ok=True)
                
                # Create empty file with header
                with open(file_path, 'w') as f:
                    f.write("Timestamp,PowerPercentage,RawPotValue\n")
                print(f"Created new power log file: {file_path}")
            except Exception as e:
                print(f"Error creating power file: {str(e)}")
        
        if not os.path.exists(file_path):
            print(f"No power log found for date: {selected_date}")
            return pd.DataFrame()
        
        # Read CSV file with explicit parsing of Timestamp column
        try:
            # Check if file is empty
            if os.path.getsize(file_path) == 0:
                print(f"Power log file is empty: {file_path}")
                # Create file with header if it's empty
                with open(file_path, 'w') as f:
                    f.write("Timestamp,PowerPercentage,RawPotValue\n")
                return pd.DataFrame(columns=['Timestamp', 'PowerPercentage', 'RawPotValue'])
            
            # Read with explicit datetime parsing for Timestamp column
            df = pd.read_csv(file_path, parse_dates=['Timestamp'])
            
            # If file only has a header but no data
            if df.empty:
                print(f"Power log file has header but no data: {file_path}")
                return pd.DataFrame(columns=['Timestamp', 'PowerPercentage', 'RawPotValue'])
                
            # Ensure Timestamp column exists and is properly formatted
            if 'Timestamp' not in df.columns:
                print(f"Missing Timestamp column in power data")
                return pd.DataFrame()
            
            # Ensure Timestamp is datetime type (in case parse_dates didn't work)
            if not pd.api.types.is_datetime64_any_dtype(df['Timestamp']):
                print("Converting Timestamp to datetime format")
                df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
                # Drop rows where timestamp conversion failed
                df = df.dropna(subset=['Timestamp'])
            
            # Ensure required columns exist
            required_columns = ['PowerPercentage', 'RawPotValue']
            if not all(col in df.columns for col in required_columns):
                print(f"Missing required columns in power data. Found columns: {df.columns}")
                return pd.DataFrame()
            
            # Convert PowerPercentage to numeric, handling any errors
            df['PowerPercentage'] = pd.to_numeric(df['PowerPercentage'], errors='coerce')
            
            # Sort by timestamp
            df.sort_values('Timestamp', inplace=True)
            
            # Debug information
            print(f"Successfully loaded power data:")
            print(f"Shape: {df.shape}")
            print(f"Columns: {df.columns}")
            if not df.empty:
                print(f"Date range: {df['Timestamp'].min()} to {df['Timestamp'].max()}")
                print(f"Power range: {df['PowerPercentage'].min():.1f}% to {df['PowerPercentage'].max():.1f}%")
            
            return df
            
        except pd.errors.EmptyDataError:
            print(f"Power log file is empty: {file_path}")
            # Create file with header if it's empty
            with open(file_path, 'w') as f:
                f.write("Timestamp,PowerPercentage,RawPotValue\n")
            return pd.DataFrame(columns=['Timestamp', 'PowerPercentage', 'RawPotValue'])
        except Exception as e:
            print(f"Error reading power CSV file: {e}")
            print(traceback.format_exc())
            return pd.DataFrame()
            
    except Exception as e:
        print(f"Error loading ventilation power data: {e}")
        print(traceback.format_exc())
        return pd.DataFrame()

def _ensure_current_day_file(data_dir, prefix):
    """Create an empty file with header for the current day if it doesn't exist"""
    current_date = datetime.now().strftime('%Y-%m-%d')
    file_path = os.path.join(data_dir, f"{prefix}_{current_date}.csv")
    
    if os.path.exists(file_path):
        return file_path
        
    try:
        # Create directory if it doesn't exist
        os.makedirs(data_dir, exist_ok=True)
        
        # Create file with appropriate header
        if prefix == 'humidity':
            header = "Datum,Uhrzeit,Sensor1_Temp,Sensor1_Hum,Sensor2_Temp,Sensor2_Hum,Sensor3_Temp,Sensor3_Hum,Sensor4_Temp,Sensor4_Hum,Sensor5_Temp,Sensor5_Hum\n"
        elif prefix == 'soil_data':
            header = "Date,Time,Moisture1,Temperature1,Moisture2,Temperature2\n"
        elif prefix == 'potentiometer_power':
            header = "Timestamp,PowerPercentage,RawPotValue\n"
        else:
            header = ""
            
        with open(file_path, 'w') as f:
            f.write(header)
        print(f"Created empty {prefix} file with header: {file_path}")
        return file_path
    except Exception as e:
        print(f"Error creating empty file for {prefix}: {str(e)}")
        return None
        
def load_csv_files(data_dir, prefix):
    """Load all available CSV files from the data directory with improved sorting and validation."""
    if not os.path.exists(data_dir):
        print(f"Directory not found: {data_dir}")
        return []
    
    # Updated to handle multiple possible prefixes
    prefixes = {
        'humidity': os.path.join(data_dir, f'humidity_*.csv'),
        'soil_data': os.path.join(data_dir, f'soil_data_*.csv'),
        'potentiometer_power': os.path.join('/home/johagy/ventilation_logs', f'potentiometer_power_*.csv')
    }
    
    pattern = prefixes.get(prefix)
    if not pattern:
        print(f"No pattern found for prefix: {prefix}")
        return []
    
    files = glob.glob(pattern)
    
    if not files:
        print(f"No files found matching pattern: {pattern}")
        return []
    
    # Sort files by date in filename
    def extract_date(filename):
        # Handle different possible filename formats
        date_patterns = [
            r'_(\d{4}-\d{2}-\d{2})',  # Standard YYYY-MM-DD format
            r'_(\d{2}/\d{2}/\d{2})'   # Alternative DD/MM/YY format
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, os.path.basename(filename))
            if match:
                try:
                    # Attempt to parse the date string
                    date_str = match.group(1)
                    
                    # Try different parsing formats
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    except ValueError:
                        date_obj = datetime.strptime(date_str, '%d/%m/%y')
                    
                    return date_obj.strftime('%Y-%m-%d')
                except ValueError:
                    print(f"Warning: Invalid date format in filename: {filename}")
                    return '0000-00-00'
        
        print(f"Warning: Could not extract date from filename: {filename}")
        return '0000-00-00'
    
    # Sort files by date (newest first)
    sorted_files = sorted(files, key=extract_date, reverse=True)
    
    print(f"\nFiles sorted chronologically for {prefix} (newest first):")
    for file in sorted_files:
        print(f"  {file} (date: {extract_date(file)})")
    
    return sorted_files

def load_dht22_data(selected_file):
    """Load and process DHT22 sensor data with improved error handling and validation."""
    try:
        print(f"\nAttempting to load DHT22 data from: {selected_file}")
        
        if not os.path.exists(selected_file):
            print(f"Error: File does not exist: {selected_file}")
            return pd.DataFrame()
        
        # Read the file in chunks to handle changing column counts
        chunks = []
        header_8cols = ['Datum', 'Uhrzeit', 'Sensor1_Temp', 'Sensor1_Hum', 
                       'Sensor2_Temp', 'Sensor2_Hum', 'Sensor3_Temp', 'Sensor3_Hum']
        header_12cols = ['Datum', 'Uhrzeit', 'Sensor1_Temp', 'Sensor1_Hum', 
                        'Sensor2_Temp', 'Sensor2_Hum', 'Sensor3_Temp', 'Sensor3_Hum',
                        'Sensor4_Temp', 'Sensor4_Hum', 'Sensor5_Temp', 'Sensor5_Hum']
        
        current_line = 0
        buffer = []
        
        with open(selected_file, 'r') as f:
            # Skip original header
            next(f)
            
            for line in f:
                current_line += 1
                fields = line.strip().split(',')
                
                # Skip empty lines
                if not fields or all(not field.strip() for field in fields):
                    continue
                
                if len(fields) == 8:
                    # Old format line
                    row = {col: val for col, val in zip(header_8cols, fields)}
                    # Add NaN for missing sensors
                    for col in header_12cols[8:]:
                        row[col] = np.nan
                    buffer.append(row)
                elif len(fields) == 12:
                    # New format line
                    row = {col: val for col, val in zip(header_12cols, fields)}
                    buffer.append(row)
                else:
                    print(f"Warning: Skipping malformed line {current_line} with {len(fields)} fields")
                    continue
        
        if not buffer:
            print("Warning: No valid data rows found in file")
            return pd.DataFrame()
        
        # Convert buffer to DataFrame
        df = pd.DataFrame(buffer)
        
        # Convert numeric columns
        numeric_cols = [col for col in df.columns if 'Temp' in col or 'Hum' in col]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Parse timestamp with flexible format handling
        try:
            df['Timestamp'] = pd.to_datetime(df['Datum'] + ' ' + df['Uhrzeit'], format='%d/%m/%y %H:%M')
        except Exception as e:
            print(f"First timestamp format failed, trying alternative: {str(e)}")
            try:
                df['Timestamp'] = pd.to_datetime(df['Datum'] + ' ' + df['Uhrzeit'], format='%Y-%m-%d %H:%M')
            except Exception as e:
                print(f"Error parsing timestamps: {str(e)}")
                return pd.DataFrame()
        
        # Rename columns to standardized names
        column_mapping = {
            'Sensor1_Temp': 'TemperatureSensor1',
            'Sensor1_Hum': 'HumiditySensor1',
            'Sensor2_Temp': 'TemperatureSensor2',
            'Sensor2_Hum': 'HumiditySensor2',
            'Sensor3_Temp': 'TemperatureSensor3',
            'Sensor3_Hum': 'HumiditySensor3',
            'Sensor4_Temp': 'TemperatureSensor4',
            'Sensor4_Hum': 'HumiditySensor4',
            'Sensor5_Temp': 'TemperatureSensor5',
            'Sensor5_Hum': 'HumiditySensor5'
        }
        df.rename(columns=column_mapping, inplace=True)
        
        # Sort by timestamp to ensure chronological order
        df.sort_values('Timestamp', inplace=True)
        
        print(f"Successfully loaded data with shape: {df.shape}")
        print(f"Available columns: {sorted(df.columns.tolist())}")
        print(f"Date range: {df['Timestamp'].min()} to {df['Timestamp'].max()}")
        
        return df
        
    except Exception as e:
        print(f"Error loading DHT22 file: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        return pd.DataFrame()

def load_soil_data(date_str):
    """Load soil data with improved error handling and validation."""
    try:
        if date_str is None:
            return pd.DataFrame()
            
        # Extract date from filename if full path is provided
        if '/' in date_str:
            date_str = date_str.split('/')[-1].replace('soil_data_', '').replace('.csv', '')
            
        soil_file = os.path.join(SOIL_DATA_DIR, f'soil_data_{date_str}.csv')
        print(f"Loading soil data from: {soil_file}")
        
        if not os.path.exists(soil_file):
            print(f"Soil data file not found: {soil_file}")
            return pd.DataFrame()
            
        # Read the file with error handling
        try:
            df = pd.read_csv(soil_file)
        except pd.errors.EmptyDataError:
            print(f"Empty soil data file: {soil_file}")
            return pd.DataFrame()
        except Exception as e:
            print(f"Error reading soil data file: {str(e)}")
            return pd.DataFrame()
            
        print(f"Columns found: {df.columns.tolist()}")
        
        # Verify required columns exist
        required_cols = ['Date', 'Time']
        if not all(col in df.columns for col in required_cols):
            print(f"Missing required columns in soil data")
            return pd.DataFrame()
            
        # Parse timestamp with flexible format handling
        try:
            df['Timestamp'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%d/%m/%y %H:%M')
        except Exception as e:
            print(f"First timestamp format failed, trying alternative: {str(e)}")
            try:
                df['Timestamp'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%Y-%m-%d %H:%M')
            except Exception as e:
                print(f"Error parsing soil data timestamps: {str(e)}")
                return pd.DataFrame()
                
        # Convert numeric columns
        numeric_cols = [col for col in df.columns if col.startswith(('Moisture', 'Temperature'))]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        # Sort by timestamp
        df.sort_values('Timestamp', inplace=True)
        
        return df
        
    except Exception as e:
        print(f"Error loading soil data: {str(e)}")
        return pd.DataFrame()

def get_latest_images():
    """Get the most recent image from each camera with improved error handling."""
    base_dir = Path.home() / "timelapse"
    latest_images = {}
    
    print(f"Checking for images in: {base_dir}")
    
    if not base_dir.exists():
        print(f"Timelapse directory not found: {base_dir}")
        return latest_images
    
    try:
        dated_folders = sorted([d for d in base_dir.iterdir() if d.is_dir()], reverse=True)
        print(f"Found {len(dated_folders)} dated folders")
        
        for folder in dated_folders:
            print(f"Checking folder: {folder}")
            for port in [0, 1]:
                if port not in latest_images:
                    pattern = f"camera_port_{port}_*.jpg"
                    images = sorted(folder.glob(pattern), reverse=True)
                    
                    if images:
                        try:
                            image_path = images[0]
                            print(f"Found image for port {port}: {image_path}")
                            
                            if not image_path.exists():
                                print(f"Image file doesn't exist: {image_path}")
                                continue
                                
                            with open(image_path, 'rb') as img_file:
                                encoded_image = base64.b64encode(img_file.read()).decode('utf-8')
                                timestamp = re.search(r'(\d{8}_\d{6})', image_path.name)
                                if timestamp:
                                    ts = datetime.strptime(timestamp.group(1), '%Y%m%d_%H%M%S')
                                    timestamp_str = ts.strftime('%d.%m.%Y %H:%M:%S')
                                else:
                                    timestamp_str = "Unknown"
                                    
                                latest_images[port] = {
                                    'image': encoded_image,
                                    'timestamp': timestamp_str
                                }
                                print(f"Successfully loaded image for port {port}")
                        except Exception as e:
                            print(f"Error processing image {images[0]}: {e}")
                    else:
                        print(f"No images found for port {port} in folder {folder}")
    
    except Exception as e:
        print(f"Error scanning timelapse directory: {e}")
    
    return latest_images

def check_data_directories():
    """Verify data directories exist and are accessible."""
    directories = {
        'DHT22': DHT22_DATA_DIR,
        'Soil': SOIL_DATA_DIR,
        'Timelapse': str(Path.home() / "timelapse")
    }
    
    status = {}
    for name, path in directories.items():
        exists = os.path.exists(path)
        status[name] = {
            'exists': exists,
            'path': path,
            'readable': os.access(path, os.R_OK) if exists else False
        }
        
    return status

def calculate_vpd(temperature, relative_humidity):
    """Calculate VPD (Vapor Pressure Deficit) in kPa"""
    svp = 0.61078 * np.exp((17.27 * temperature) / (temperature + 237.3))
    vpd = svp * (1 - (relative_humidity / 100))
    return vpd

def calculate_stats(dht_df, soil_df):
    """Calculate statistics for all sensors."""
    stats = {
        'Spinnenfarm': {
            'Eintritt': {},
            'Austritt': {},
            'Boden': {}
        },
        'Schwarzebox': {
            'Eintritt': {},
            'Austritt': {},
            'Boden': {}
        },
        'Raum': {}
    }
    
    # DHT22 sensor stats for Spinnenfarm and Schwarzebox
    stats['Spinnenfarm']['Eintritt'] = _get_sensor_stats(dht_df, 1, 'TemperatureSensor', 'HumiditySensor')
    stats['Spinnenfarm']['Austritt'] = _get_sensor_stats(dht_df, 4, 'TemperatureSensor', 'HumiditySensor')
    
    stats['Schwarzebox']['Eintritt'] = _get_sensor_stats(dht_df, 2, 'TemperatureSensor', 'HumiditySensor')
    stats['Schwarzebox']['Austritt'] = _get_sensor_stats(dht_df, 5, 'TemperatureSensor', 'HumiditySensor')
    
    # Raum sensor stats
    raum_stats = _get_sensor_stats(dht_df, 3, 'TemperatureSensor', 'HumiditySensor')
    if raum_stats:
        stats['Raum'] = raum_stats
    
    # Soil sensor stats
    if not soil_df.empty:
        # Spinnenfarm Boden
        stats['Spinnenfarm']['Boden'] = _get_soil_stats(soil_df, 1)
        
        # Schwarzebox Boden
        stats['Schwarzebox']['Boden'] = _get_soil_stats(soil_df, 2)
    
    return stats

def _get_sensor_stats(df, sensor_id, temp_prefix, hum_prefix):
    """Helper function to extract sensor statistics"""
    temp_col = f'{temp_prefix}{sensor_id}'
    hum_col = f'{hum_prefix}{sensor_id}'
    
    if temp_col in df.columns and hum_col in df.columns:
        return {
            'Temperatur': {
                'min': f"{df[temp_col].min():.1f}°C",
                'max': f"{df[temp_col].max():.1f}°C",
                'avg': f"{df[temp_col].mean():.1f}°C"
            },
            'Luftfeuchtigkeit': {
                'min': f"{df[hum_col].min():.1f}%",
                'max': f"{df[hum_col].max():.1f}%",
                'avg': f"{df[hum_col].mean():.1f}%"
            }
        }
    return {}

def _get_soil_stats(df, sensor_id):
    """Helper function to extract soil sensor statistics"""
    moisture_col = f'Moisture{sensor_id}'
    temp_col = f'Temperature{sensor_id}'
    
    if moisture_col in df.columns and temp_col in df.columns:
        return {
            'Bodenfeuchtigkeit': {
                'min': f"{df[moisture_col].min():.0f}",
                'max': f"{df[moisture_col].max():.0f}",
                'avg': f"{df[moisture_col].mean():.0f}"
            },
            'Bodentemperatur': {
                'min': f"{df[temp_col].min():.1f}°C",
                'max': f"{df[temp_col].max():.1f}°C",
                'avg': f"{df[temp_col].mean():.1f}°C"
            }
        }
    return {}

def apply_time_range_filter(df, time_range):
    """Apply time range filter to dataframe with improved error handling"""
    if time_range != 'all' and not df.empty and 'Timestamp' in df.columns:
        try:
            # Ensure Timestamp is datetime type
            if not pd.api.types.is_datetime64_any_dtype(df['Timestamp']):
                print("Converting Timestamp to datetime format in time filter")
                df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
                # Drop rows where timestamp conversion failed
                df = df.dropna(subset=['Timestamp'])
                
            hours = int(time_range[:-1])
            cutoff = datetime.now() - timedelta(hours=hours)
            filtered_df = df[df['Timestamp'] >= cutoff]
            
            print(f"Time range filter: From {cutoff} onwards")
            print(f"Filtered data points: {len(df)} -> {len(filtered_df)}")
            
            return filtered_df
        except Exception as e:
            print(f"Error applying time filter: {e}")
            print(traceback.format_exc())
            return df
    return df

# Responsive Component Creation Functions
def create_camera_section():
    """Create responsive camera section with status indicators"""
    return html.Div([
        html.H3("Live Cameras", 
                style={'color': 'var(--text-primary)', 'marginBottom': '1rem'}),
        html.Div([
            html.Div([
                html.Div([
                    html.H4(
                        "Spinnenfarm", 
                        style={'color': 'var(--text-primary)', 'marginBottom': '0.5rem'}
                    ),
                    html.Div(
                        id='camera-1-status',
                        style={'color': 'var(--text-secondary)', 'marginBottom': '0.5rem'}
                    ),
                    html.Div(
                        id='camera-1-image',
                        className='image-container'
                    )
                ], className='camera-card mobile-padding'),
                html.Div([
                    html.H4(
                        "Schwarzebox", 
                        style={'color': 'var(--text-primary)', 'marginBottom': '0.5rem'}
                    ),
                    html.Div(
                        id='camera-0-status',
                        style={'color': 'var(--text-secondary)', 'marginBottom': '0.5rem'}
                    ),
                    html.Div(
                        id='camera-0-image',
                        className='image-container'
                    )
                ], className='camera-card mobile-padding')
            ], className='camera-grid')
        ])
    ], className='camera-section')

def create_unified_monitoring_section():
    """Create a responsive unified monitoring section with advanced gauges"""
    def create_gauge(id_prefix, label, units, min_val, max_val, optimal_ranges, current_value_id):
        """Create a gauge using Plotly's indicator gauge with more horizontal layout"""
        return html.Div([
            # Label and Value Display (side by side)
            html.Div([
                html.Label(
                    label, 
                    className='gauge-label',
                    style={
                        'fontSize': '0.75rem',
                        'lineHeight': '1',
                        'marginRight': '0.2rem',
                        'whiteSpace': 'nowrap'
                    }
                ),
                html.Div(
                    id=current_value_id,
                    className='gauge-value',
                    style={
                        'fontSize': '0.75rem',
                        'color': 'var(--accent)',
                        'lineHeight': '1',
                        'marginLeft': 'auto',
                        'fontWeight': 'bold'
                    }
                )
            ], style={
                'display': 'flex',
                'justifyContent': 'space-between',
                'alignItems': 'center',
                'width': '100%',
                'marginBottom': '1px',
                'minHeight': '16px',
                'padding': '0 2px'
            }),
            
            # Plotly Gauge (compact height)
            dcc.Graph(
                id=f'{id_prefix}-gauge',
                figure={
                    'data': [{
                        'type': 'indicator',
                        'mode': 'gauge',
                        'value': 0,  # Initial value
                        'gauge': {
                            'axis': {'range': [min_val, max_val]},
                            'bar': {'color': "darkgray"},
                            'steps': [
                                {'range': [min_val, optimal_ranges[0][0]], 'color': "#FF4444"},
                                {'range': [optimal_ranges[0][0], optimal_ranges[0][1]], 'color': "#FFA500"},
                                {'range': [optimal_ranges[0][1], optimal_ranges[1][0]], 'color': "#44FF44"},
                                {'range': [optimal_ranges[1][0], optimal_ranges[1][1]], 'color': "#FFA500"},
                                {'range': [optimal_ranges[1][1], max_val], 'color': "#FF4444"}
                            ],
                            'threshold': {
                                'line': {'color': "white", 'width': 2},
                                'thickness': 0.75,
                                'value': 0  # Will be updated by callback
                            }
                        }
                    }],
                    'layout': {
                        'height': 70, # Reduced height
                        'margin': {'l': 5, 'r': 5 , 't': 3, 'b': 3}, # Tighter margins
                        'paper_bgcolor': '#1a1a1a',
                        'font': {'color': "white", 'size': 6},
                        'showlegend': False
                    }
                },
                config={'displayModeBar': False},
                style={'width': '100%', 'height': '70px'} # Force consistent size
            ),
            
            # Units (moved to the bottom with smaller size)
            html.Div(
                units,
                style={
                    'color': 'var(--text-secondary)',
                    'fontSize': '0.6rem',
                    'textAlign': 'center',
                    'marginTop': '0px'
                }
            )
        ], className='gauge-item')

    # Now structure the monitoring sections with better grouping

    return html.Div([
        # Main Content Container
        html.Div([
            # Camera section (unchanged)
            html.Div([
                html.H3("Live Cameras", style={'color': 'var(--text-primary)', 'marginBottom': '0.5rem', 'fontSize': '1rem'}),
                html.Div(id='camera-images-container', style={'marginBottom': '1rem', 'width': '100%'})
            ]),
            
            # Sensor Data Section with improved layout
            html.Div([
                # Spinnenfarm Section
                html.Div([
                    html.H4("Spinnenfarm", style={
                        'color': 'var(--text-primary)', 
                        'textAlign': 'center', 
                        'marginBottom': '0.3rem', 
                        'fontSize': '1.1rem'
                    }),
                    
                    # Eintritt Gauges - Group in their own box
                    html.Div([
                        html.H5("Eintritt", style={
                            'color': 'var(--text-secondary)', 
                            'textAlign': 'center', 
                            'marginBottom': '0.2rem', 
                            'fontSize': '0.9rem'
                        }),
                        html.Div([
                            create_gauge(
                                'sensor1-temp', 'Temperatur', '°C', 0, 40, 
                                [(15, 20), (28, 35)], 
                                'sensor1-temp-value'
                            ),
                            create_gauge(
                                'sensor1-humidity', 'Luftfeuchte', '%', 0, 100, 
                                [(40, 50), (70, 80)], 
                                'sensor1-humidity-value'
                            ),
                            create_gauge(
                                'sensor1-vpd', 'VPD', 'kPa', 0, 3, 
                                [(0.8, 1.0), (1.2, 1.5)], 
                                'sensor1-vpd-value'
                            ),
                        ], className='gauge-row')
                    ], className='gauge-group'),
                    
                    # Austritt Gauges - Group in their own box
                    html.Div([
                        html.H5("Austritt", style={
                            'color': 'var(--text-secondary)', 
                            'textAlign': 'center', 
                            'marginBottom': '0.2rem', 
                            'fontSize': '0.9rem'
                        }),
                        html.Div([
                            create_gauge(
                                'sensor4-temp', 'Temperatur', '°C', 0, 40, 
                                [(15, 20), (28, 35)], 
                                'sensor4-temp-value'
                            ),
                            create_gauge(
                                'sensor4-humidity', 'Luftfeuchte', '%', 0, 100, 
                                [(40, 50), (70, 80)], 
                                'sensor4-humidity-value'
                            ),
                        ], className='gauge-row')
                    ], className='gauge-group'),
                    
                    # Boden Gauges - Group in their own box
                    html.Div([
                        html.H5("Boden", style={
                            'color': 'var(--text-secondary)', 
                            'textAlign': 'center', 
                            'marginBottom': '0.2rem', 
                            'fontSize': '0.9rem'
                        }),
                        html.Div([
                            create_gauge(
                                'soil1-moisture', 'Feuchte', '', 0, 1000, 
                                [(300, 400), (600, 700)], 
                                'soil1-moisture-value'
                            ),
                            create_gauge(
                                'soil1-temp', 'Temp', '°C', 0, 40, 
                                [(15, 20), (28, 35)], 
                                'soil1-temp-value'
                            ),
                        ], className='gauge-row')
                    ], className='gauge-group')
                ], className='monitoring-section'),
                
                # Schwarzebox Section
                html.Div([
                    html.H4("Schwarzebox", style={
                        'color': 'var(--text-primary)', 
                        'textAlign': 'center', 
                        'marginBottom': '0.3rem', 
                        'fontSize': '1.1rem'
                    }),
                    
                    # Eintritt Gauges
                    html.Div([
                        html.H5("Eintritt", style={
                            'color': 'var(--text-secondary)', 
                            'textAlign': 'center', 
                            'marginBottom': '0.2rem', 
                            'fontSize': '0.9rem'
                        }),
                        html.Div([
                            create_gauge(
                                'sensor2-temp', 'Temperatur', '°C', 0, 40, 
                                [(15, 20), (28, 35)], 
                                'sensor2-temp-value'
                            ),
                            create_gauge(
                                'sensor2-humidity', 'Luftfeuchte', '%', 0, 100, 
                                [(40, 50), (70, 80)], 
                                'sensor2-humidity-value'
                            ),
                            create_gauge(
                                'sensor2-vpd', 'VPD', 'kPa', 0, 3, 
                                [(0.8, 1.0), (1.2, 1.5)], 
                                'sensor2-vpd-value'
                            ),
                        ], className='gauge-row')
                    ], className='gauge-group'),
                    
                    # Austritt Gauges
                    html.Div([
                        html.H5("Austritt", style={
                            'color': 'var(--text-secondary)', 
                            'textAlign': 'center', 
                            'marginBottom': '0.2rem', 
                            'fontSize': '0.9rem'
                        }),
                        html.Div([
                            create_gauge(
                                'sensor5-temp', 'Temperatur', '°C', 0, 40, 
                                [(15, 20), (28, 35)], 
                                'sensor5-temp-value'
                            ),
                            create_gauge(
                                'sensor5-humidity', 'Luftfeuchte', '%', 0, 100, 
                                [(40, 50), (70, 80)], 
                                'sensor5-humidity-value'
                            ),
                        ], className='gauge-row')
                    ], className='gauge-group'),
                    
                    # Boden Gauges
                    html.Div([
                        html.H5("Boden", style={
                            'color': 'var(--text-secondary)', 
                            'textAlign': 'center', 
                            'marginBottom': '0.2rem', 
                            'fontSize': '0.9rem'
                        }),
                        html.Div([
                            create_gauge(
                                'soil2-moisture', 'Feuchte', '', 0, 1000, 
                                [(300, 400), (600, 700)], 
                                'soil2-moisture-value'
                            ),
                            create_gauge(
                                'soil2-temp', 'Temp', '°C', 0, 40, 
                                [(15, 20), (28, 35)], 
                                'soil2-temp-value'
                            ),
                        ], className='gauge-row')
                    ], className='gauge-group')
                ], className='monitoring-section'),
                
                # Raum Section
                html.Div([
                    html.H4("Raum", style={
                        'color': 'var(--text-primary)', 
                        'textAlign': 'center', 
                        'marginBottom': '0.3rem', 
                        'fontSize': '1.1rem'
                    }),
                    html.Div([
                        html.Div([
                            create_gauge(
                                'sensor3-temp', 'Temperatur', '°C', 0, 40, 
                                [(15, 20), (28, 35)], 
                                'sensor3-temp-value'
                            ),
                            create_gauge(
                                'sensor3-humidity', 'Luftfeuchte', '%', 0, 100, 
                                [(40, 50), (70, 80)], 
                                'sensor3-humidity-value'
                            ),
                            create_gauge(
                                'sensor3-vpd', 'VPD', 'kPa', 0, 3, 
                                [(0.8, 1.0), (1.2, 1.5)], 
                                'sensor3-vpd-value'
                            )
                        ], className='gauge-row')
                    ], className='gauge-group')
                ], className='monitoring-section')
            ])
        ])
    ], className='mobile-padding')

def create_ventilation_control():
    """Create responsive ventilation control panel with better mobile layout"""
    return html.Div([
        html.H4("Lüftung", style={
            'color': 'var(--text-primary)',
            'marginBottom': '0.1rem',
            'fontSize': '0.8rem'
        }),
        html.Div([
            # Manual Control
            html.Div([
                html.Div([
                    html.Label("Geschwindigkeit", style={
                        'color': 'var(--text-secondary)',
                        'fontSize': '0.75rem',
                        'width': '50%'
                    }),
                    html.Span(
                        id='ventilation-speed-display',
                        style={
                            'color': 'var(--accent)',
                            'fontSize': '0.75rem',
                            'marginLeft': 'auto'
                        }
                    )
                ], className='form-row'),
                
                dcc.Slider(
                    id='ventilation-speed-slider',
                    min=0,
                    max=100,
                    step=1,
                    value=0,
                    marks={
                        0: '0%',
                        25: '25%',
                        50: '50%',
                        75: '75%',
                        100: '100%'
                    },
                    disabled=False,
                    className='ventilation-slider'
                )
            ], className='ventilation-controls-item'),

            # Auto Control - more compact
            html.Div([
                html.Div([
                    html.Label("VPD Automatik", style={
                        'color': 'var(--text-secondary)',
                        'fontSize': '0.75rem',
                        'width': '50%'
                    }),
                    daq.BooleanSwitch(
                        id='ventilation-auto-switch',
                        on=False,
                        color='var(--accent)'
                    )
                ], className='form-row'),
                
                html.Div([
                    html.Label("Ziel VPD (kPa)", style={
                        'color': 'var(--text-secondary)',
                        'fontSize': '0.75rem',
                        'width': '50%'
                    }),
                    dcc.Input(
                        id='ventilation-target-vpd',
                        type='number',
                        min=0.4,
                        max=2.0,
                        step=0.1,
                        value=1.0,
                        className='responsive-input'
                    )
                ], className='form-row')
            ], className='ventilation-controls-item'),
            
            html.Div(
                id='ventilation-status',
                className='ventilation-status'
            )
        ], className='ventilation-controls compact-controls')
    ], className='control-item')
    
def create_unified_control_panel():
    """Create an ultra-compact control panel for all devices"""
    return html.Div([
        # Main Container
        html.Div([
            # Header - smaller and more compact
            html.H2("System Controls", style={
                'color': 'var(--accent)',
                'marginBottom': '0.15rem',
                'fontSize': '0.8rem',
                'textAlign': 'center'
            }),
            
            # Controls Layout - two column grid
            html.Div([
                # Left panel - Spinnenfarm
                html.Div([
                    # Header
                    html.H3("Spinnenfarm", style={
                        'color': 'var(--text-primary)',
                        'marginBottom': '0.1rem',
                        'fontSize': '0.8rem',
                        'textAlign': 'center'
                    }),
                    
                    # Combined controls in a single vertical stack
                    html.Div([
                        # Valve section
                        html.Div([
                            # Title and controls in one row
                            html.Div([
                                html.H4("Ventil", style={
                                    'color': 'var(--text-primary)',
                                    'fontSize': '0.7rem',
                                    'margin': '0',
                                    'width': '20%'
                                }),
                                html.Div([
                                    html.Label("Min", style={
                                        'color': 'var(--text-secondary)',
                                        'fontSize': '0.65rem',
                                        'marginRight': '2px'
                                    }),
                                    dcc.Input(
                                        id='valve-1-duration',
                                        type='number',
                                        min=1,
                                        max=60,
                                        value=5,
                                        className='responsive-input',
                                        style={'width': '35px'}
                                    ),
                                    daq.PowerButton(
                                        id='valve-1-power',
                                        on=False,
                                        color='var(--accent)',
                                        size=20,
                                        style={'marginLeft': '4px'}
                                    )
                                ], style={'display': 'flex', 'alignItems': 'center', 'width': '80%'})
                            ], className='form-row'),
                            
                            html.Div(
                                id='valve-1-timer',
                                style={'color': 'var(--text-secondary)', 'fontSize': '0.6rem', 'height': '12px'}
                            ),
                            
                            # Schedule in one row
                            html.Div([
                                html.Label("Zeitplan", style={
                                    'color': 'var(--text-secondary)',
                                    'fontSize': '0.65rem',
                                    'width': '30%'
                                }),
                                daq.BooleanSwitch(
                                    id='valve-1-schedule-switch',
                                    on=False,
                                    color='var(--accent)'
                                ),
                                dcc.Input(
                                    id='valve-1-schedule-time',
                                    type='text',
                                    placeholder='HH:MM',
                                    className='responsive-input',
                                    style={'marginLeft': '4px', 'width': '45px'}
                                )
                            ], className='form-row'),
                            
                            html.Div(
                                id='valve-1-schedule-status',
                                style={'color': 'var(--text-secondary)', 'fontSize': '0.6rem', 'height': '12px'}
                            )
                        ], style={'borderBottom': '1px solid var(--border)', 'paddingBottom': '0.1rem', 'marginBottom': '0.1rem'}),
                        
                        # Light section
                        html.Div([
                            # Title and schedule switch in one row
                            html.Div([
                                html.H4("Light", style={
                                    'color': 'var(--text-primary)',
                                    'fontSize': '0.7rem',
                                    'margin': '0',
                                    'width': '20%'
                                }),
                                html.Div([
                                    html.Label("Zeitplan", style={
                                        'color': 'var(--text-secondary)',
                                        'fontSize': '0.65rem',
                                        'marginRight': '4px'
                                    }),
                                    daq.BooleanSwitch(
                                        id='light-schedule-switch',
                                        on=False,
                                        color='var(--accent)'
                                    )
                                ], style={'display': 'flex', 'alignItems': 'center', 'width': '80%'})
                            ], className='form-row'),
                            
                            # Time inputs in one row
                            html.Div([
                                html.Label("Ein", style={
                                    'color': 'var(--text-secondary)',
                                    'fontSize': '0.65rem',
                                    'width': '15%'
                                }),
                                dcc.Input(
                                    id='light-on-time',
                                    type='text',
                                    value='06:00',
                                    className='responsive-input',
                                    style={'width': '45px'}
                                ),
                                html.Label("Aus", style={
                                    'color': 'var(--text-secondary)',
                                    'fontSize': '0.65rem',
                                    'width': '15%',
                                    'textAlign': 'right',
                                    'marginLeft': '4px'
                                }),
                                dcc.Input(
                                    id='light-off-time',
                                    type='text',
                                    value='00:00',
                                    className='responsive-input',
                                    style={'width': '45px'}
                                )
                            ], className='form-row'),
                            
                            html.Div(
                                id='light-schedule-status',
                                style={'color': 'var(--text-secondary)', 'fontSize': '0.6rem', 'height': '12px'}
                            )
                        ], style={'borderBottom': '1px solid var(--border)', 'paddingBottom': '0.1rem', 'marginBottom': '0.1rem'})
                    ], className='control-panel-content')
                ], className='control-panel-section'),
                
                # Right panel - Schwarzebox - similar compact structure
                html.Div([
                    # Header
                    html.H3("Schwarzebox", style={
                        'color': 'var(--text-primary)',
                        'marginBottom': '0.1rem',
                        'fontSize': '0.8rem',
                        'textAlign': 'center'
                    }),
                    
                    # Combined controls in a single vertical stack
                    html.Div([
                        # Valve section
                        html.Div([
                            # Title and controls in one row
                            html.Div([
                                html.H4("Ventil", style={
                                    'color': 'var(--text-primary)',
                                    'fontSize': '0.7rem',
                                    'margin': '0',
                                    'width': '20%'
                                }),
                                html.Div([
                                    html.Label("Min", style={
                                        'color': 'var(--text-secondary)',
                                        'fontSize': '0.65rem',
                                        'marginRight': '2px'
                                    }),
                                    dcc.Input(
                                        id='valve-2-duration',
                                        type='number',
                                        min=1,
                                        max=60,
                                        value=5,
                                        className='responsive-input',
                                        style={'width': '35px'}
                                    ),
                                    daq.PowerButton(
                                        id='valve-2-power',
                                        on=False,
                                        color='var(--accent)',
                                        size=20,
                                        style={'marginLeft': '4px'}
                                    )
                                ], style={'display': 'flex', 'alignItems': 'center', 'width': '80%'})
                            ], className='form-row'),
                            
                            html.Div(
                                id='valve-2-timer',
                                style={'color': 'var(--text-secondary)', 'fontSize': '0.6rem', 'height': '12px'}
                            ),
                            
                            # Schedule in one row
                            html.Div([
                                html.Label("Zeitplan", style={
                                    'color': 'var(--text-secondary)',
                                    'fontSize': '0.65rem',
                                    'width': '30%'
                                }),
                                daq.BooleanSwitch(
                                    id='valve-2-schedule-switch',
                                    on=False,
                                    color='var(--accent)'
                                ),
                                dcc.Input(
                                    id='valve-2-schedule-time',
                                    type='text',
                                    placeholder='HH:MM',
                                    className='responsive-input',
                                    style={'marginLeft': '4px', 'width': '45px'}
                                )
                            ], className='form-row'),
                            
                            html.Div(
                                id='valve-2-schedule-status',
                                style={'color': 'var(--text-secondary)', 'fontSize': '0.6rem', 'height': '12px'}
                            )
                        ], style={'borderBottom': '1px solid var(--border)', 'paddingBottom': '0.1rem', 'marginBottom': '0.1rem'}),
                        
                        # Light section
                        html.Div([
                            # Title and schedule switch in one row
                            html.Div([
                                html.H4("Light", style={
                                    'color': 'var(--text-primary)',
                                    'fontSize': '0.7rem',
                                    'margin': '0',
                                    'width': '20%'
                                }),
                                html.Div([
                                    html.Label("Zeitplan", style={
                                        'color': 'var(--text-secondary)',
                                        'fontSize': '0.65rem',
                                        'marginRight': '4px'
                                    }),
                                    daq.BooleanSwitch(
                                        id='light2-schedule-switch',
                                        on=False,
                                        color='var(--accent)'
                                    )
                                ], style={'display': 'flex', 'alignItems': 'center', 'width': '80%'})
                            ], className='form-row'),
                            
                            # Time inputs in one row
                            html.Div([
                                html.Label("Ein", style={
                                    'color': 'var(--text-secondary)',
                                    'fontSize': '0.65rem',
                                    'width': '15%'
                                }),
                                dcc.Input(
                                    id='light2-on-time',
                                    type='text',
                                    value='06:00',
                                    className='responsive-input',
                                    style={'width': '45px'}
                                ),
                                html.Label("Aus", style={
                                    'color': 'var(--text-secondary)',
                                    'fontSize': '0.65rem',
                                    'width': '15%',
                                    'textAlign': 'right',
                                    'marginLeft': '4px'
                                }),
                                dcc.Input(
                                    id='light2-off-time',
                                    type='text',
                                    value='00:00',
                                    className='responsive-input',
                                    style={'width': '45px'}
                                )
                            ], className='form-row'),
                            
                            html.Div(
                                id='light2-schedule-status',
                                style={'color': 'var(--text-secondary)', 'fontSize': '0.6rem', 'height': '12px'}
                            )
                        ], style={'borderBottom': '1px solid var(--border)', 'paddingBottom': '0.1rem', 'marginBottom': '0.1rem'})
                    ], className='control-panel-content')
                ], className='control-panel-section')
            ], className='control-panel-grid'),
            
            # Ventilation controls - ultra compact
            html.Div([
                html.H3("Lüftung", style={
                    'color': 'var(--text-primary)',
                    'marginBottom': '0.1rem',
                    'fontSize': '0.8rem',
                    'textAlign': 'center'
                }),
                
                # Speed section
                html.Div([
                    # Speed label and display
                    html.Div([
                        html.Label("Geschwindigkeit", style={
                            'color': 'var(--text-secondary)',
                            'fontSize': '0.65rem',
                            'width': '50%'
                        }),
                        html.Span(
                            id='ventilation-speed-display',
                            style={
                                'color': 'var(--accent)',
                                'fontSize': '0.65rem',
                                'marginLeft': 'auto'
                            }
                        )
                    ], className='form-row', style={'marginBottom': '0'}),
                    
                    # Slider
                    dcc.Slider(
                        id='ventilation-speed-slider',
                        min=0,
                        max=100,
                        step=5,
                        value=0,
                        marks={
                            0: '0',
                            50: '50',
                            100: '100'
                        },
                        disabled=False,
                        className='ventilation-slider'
                    )
                ], style={'marginBottom': '0.1rem'}),
                
                # Auto control
                html.Div([
                    # VPD auto switch
                    html.Div([
                        html.Label("VPD Auto", style={
                            'color': 'var(--text-secondary)',
                            'fontSize': '0.65rem',
                            'width': '30%'
                        }),
                        daq.BooleanSwitch(
                            id='ventilation-auto-switch',
                            on=False,
                            color='var(--accent)'
                        ),
                        html.Label("Ziel", style={
                            'color': 'var(--text-secondary)',
                            'fontSize': '0.65rem',
                            'width': '15%',
                            'textAlign': 'right',
                            'marginLeft': '4px'
                        }),
                        dcc.Input(
                            id='ventilation-target-vpd',
                            type='number',
                            min=0.4,
                            max=2.0,
                            step=0.1,
                            value=1.0,
                            className='responsive-input',
                            style={'width': '35px'}
                        ),
                        html.Label("kPa", style={
                            'color': 'var(--text-secondary)',
                            'fontSize': '0.65rem',
                            'marginLeft': '2px'
                        })
                    ], className='form-row'),
                    
                    html.Div(
                        id='ventilation-status',
                        style={'color': 'var(--text-secondary)', 'fontSize': '0.6rem', 'height': '12px'}
                    )
                ])
            ], className='ventilation-panel')
        ], className='mobile-padding'),
        
        # Ultra compact file selector
        html.Div([
            # File selectors in a compact grid
            html.Div([
                # DHT22 Selector
                html.Div([
                    html.Label('DHT22', className='selector-label'),
                    dcc.Dropdown(
                        id='file-selector',
                        options=[],  # Will be populated by callback
                        clearable=False,
                        className='custom-dropdown'
                    )
                ], className='selector-item'),
                
                # Soil Selector
                html.Div([
                    html.Label('Boden', className='selector-label'),
                    dcc.Dropdown(
                        id='soil-file-selector',
                        options=[],  # Will be populated by callback
                        clearable=False,
                        className='custom-dropdown'
                    )
                ], className='selector-item'),
                
                # Power Selector
                html.Div([
                    html.Label('Lüftung', className='selector-label'),
                    dcc.Dropdown(
                        id='power-file-selector',
                        options=[],  # Will be populated by callback
                        clearable=False,
                        className='custom-dropdown'
                    )
                ], className='selector-item'),
                
                # Time Range in same row for medium screens and its own row for very small screens
                html.Div([
                    html.Label('Zeit', className='selector-label'),
                    dcc.RadioItems(
                        id='time-range',
                        options=[
                            {'label': '6h', 'value': '6h'},
                            {'label': '12h', 'value': '12h'},
                            {'label': '24h', 'value': '24h'},
                            {'label': 'All', 'value': 'all'}
                        ],
                        value='all',
                        className='time-range-radio',
                        inputStyle={'marginRight': '2px'},
                        labelStyle={'marginRight': '4px', 'fontSize': '0.65rem'}
                    )
                ], className='selector-item time-selector')
            ], className='file-selector-grid')
        ], className='mobile-padding')
    ], className='control-panel')

def create_file_selectors():
    """Create responsive file selector dropdowns with improved mobile styling"""
    # Get files
    dht_files = load_csv_files(DHT22_DATA_DIR, 'humidity')
    soil_files = load_csv_files(SOIL_DATA_DIR, 'soil_data')
    power_files = load_csv_files('/home/johagy/ventilation_logs', 'potentiometer_power')
    
    # Get current files
    current_dht = get_current_day_file(DHT22_DATA_DIR, 'humidity')
    current_soil = get_current_day_file(SOIL_DATA_DIR, 'soil_data')
    current_date = datetime.now().strftime('%Y-%m-%d')
    current_power = os.path.join('/home/johagy/ventilation_logs', f'potentiometer_power_{current_date}.csv')
    if not os.path.exists(current_power):
        current_power = None
    
    def format_date_label(filepath):
        match = re.search(r'_(\d{4}-\d{2}-\d{2})', filepath)
        return match.group(1).replace('-', '.') if match else filepath
    
    return html.Div([
        # Responsive container for all selectors
        html.Div([
            # DHT22 Selector
            html.Div([
                html.Label('DHT22:', className='selector-label'),
                dcc.Dropdown(
                    id='file-selector',
                    options=[{'label': format_date_label(f), 'value': f} for f in dht_files],
                    value=current_dht or (dht_files[-1] if dht_files else None),
                    clearable=False,
                    className='custom-dropdown'
                )
            ], className='selector-item'),
            
            # Soil Selector
            html.Div([
                html.Label('Boden:', className='selector-label'),
                dcc.Dropdown(
                    id='soil-file-selector',
                    options=[{'label': format_date_label(f), 'value': f} for f in soil_files],
                    value=current_soil or (soil_files[-1] if soil_files else None),
                    clearable=False,
                    className='custom-dropdown'
                )
            ], className='selector-item'),
            
            # Power Selector
            html.Div([
                html.Label('Lüftung:', className='selector-label'),
                dcc.Dropdown(
                    id='power-file-selector',
                    options=[{'label': format_date_label(f), 'value': f} for f in power_files],
                    value=current_power or (power_files[-1] if power_files else None),
                    clearable=False,
                    className='custom-dropdown'
                )
            ], className='selector-item'),
            
            # Time Range in same row for medium screens and its own row for very small screens
            html.Div([
                html.Label('Zeit:', className='selector-label'),
                dcc.RadioItems(
                    id='time-range',
                    options=[
                        {'label': '6h', 'value': '6h'},
                        {'label': '12h', 'value': '12h'},
                        {'label': '24h', 'value': '24h'},
                        {'label': 'All', 'value': 'all'}
                    ],
                    value='all',
                    className='time-range-radio',
                    inputStyle={'margin-right': '3px', 'cursor': 'pointer'},
                    labelStyle={'margin-right': '6px', 'cursor': 'pointer', 'fontSize': '0.7rem'}
                )
            ], className='selector-item time-selector')
        ], className='file-selector-grid')
    ], className='mobile-padding')

# Figure Creation Functions
# Helper function for creating optimized layouts
def create_optimized_figure_layout(title, y_title, y_range=None):
    """Create an optimized figure layout that uses space efficiently"""
    layout = {
        'title': title,
        'title_font_size': 14,
        'xaxis_title': 'Zeit',
        'xaxis_title_font_size': 10,
        'yaxis_title': y_title,
        'yaxis_title_font_size': 10,
        'paper_bgcolor': '#1a1a1a',
        'plot_bgcolor': '#1a1a1a',
        'font': dict(color='white', size=10),
        'xaxis': dict(
            gridcolor='#404040',
            tickfont=dict(size=9)
        ),
        'yaxis': dict(
            gridcolor='#404040',
            tickfont=dict(size=9)
        ),
        'margin': dict(l=35, r=15, t=30, b=30),
        'legend': dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            font=dict(size=10)
        ),
        'autosize': True
    }
    
    # Add y-range if provided
    if y_range:
        layout['yaxis_range'] = y_range
        
    return layout

# Updated figure creation functions

def create_temperature_figure(dht_df):
    """Create temperature plot for air temperature sensors with optimized layout."""
    fig = go.Figure()
    
    # Add DHT22 temperature traces for all 5 sensors
    for sensor_id in [1, 2, 3, 4, 5]:
        temp_col = f'TemperatureSensor{sensor_id}'
        if temp_col in dht_df.columns:
            fig.add_trace(go.Scatter(
                x=dht_df['Timestamp'],
                y=dht_df[temp_col],
                name=f"{SENSOR_NAMES[sensor_id]}",
                mode='lines',
                line=dict(shape='hvh')
            ))
    
    fig.add_hrect(
        y0=20, y1=28,
        fillcolor="green", opacity=0.1,
        layer="below", line_width=0,
        annotation_text="Optimal",
        annotation_position="left"
    )
    
    # Apply optimized layout
    fig.update_layout(
        **create_optimized_figure_layout('Lufttemperatur', 'Temperatur (°C)', [15, 30])
    )
    
    return fig

def create_humidity_figure(dht_df):
    """Create humidity plot with optimized layout."""
    fig = go.Figure()
    
    for sensor_id in [1, 2, 3, 4, 5]:
        hum_col = f'HumiditySensor{sensor_id}'
        if hum_col in dht_df.columns:
            fig.add_trace(go.Scatter(
                x=dht_df['Timestamp'],
                y=dht_df[hum_col],
                name=SENSOR_NAMES[sensor_id],
                mode='lines'
            ))
    
    fig.add_hrect(
        y0=40, y1=70,
        fillcolor="green", opacity=0.1,
        layer="below", line_width=0,
        annotation_text="Optimal",
        annotation_position="left"
    )
    
    # Apply optimized layout
    fig.update_layout(
        **create_optimized_figure_layout('Luftfeuchtigkeitsverlauf', 'Luftfeuchtigkeit (%)', [30, 100])
    )
    
    return fig

def create_vpd_figure(dht_df):
    """Create VPD plot with optimized layout."""
    fig = go.Figure()
    
    for sensor_id in [1, 2, 3]:
        vpd_values = calculate_vpd(
            dht_df[f'TemperatureSensor{sensor_id}'],
            dht_df[f'HumiditySensor{sensor_id}']
        )
        
        fig.add_trace(go.Scatter(
            x=dht_df['Timestamp'],
            y=vpd_values,
            name=f"{SENSOR_NAMES[sensor_id]}",
            mode='lines'
        ))
    
    # Add optimal VPD range
    fig.add_hrect(
        y0=0.8, y1=1.2,
        fillcolor="green", opacity=0.1,
        layer="below", line_width=0,
        annotation_text="Optimal",
        annotation_position="left"
    )
    
    # Apply optimized layout
    fig.update_layout(
        **create_optimized_figure_layout('VPD (Vapor Pressure Deficit)', 'VPD (kPa)', [0, 3])
    )
    
    return fig

def create_soil_moisture_figure(soil_df):
    """Create soil moisture plot with optimized layout."""
    fig = go.Figure()
    
    if not soil_df.empty:
        for sensor_id in [1, 2]:
            moisture_col = f'Moisture{sensor_id}'
            if moisture_col in soil_df.columns:
                # Convert moisture values to numeric, handling errors
                soil_df[moisture_col] = pd.to_numeric(soil_df[moisture_col], errors='coerce')
                
                # Remove NaN values
                valid_data = soil_df.dropna(subset=[moisture_col, 'Timestamp'])
                
                if not valid_data.empty:
                    fig.add_trace(go.Scatter(
                        x=valid_data['Timestamp'],
                        y=valid_data[moisture_col],
                        name=SENSOR_NAMES[f'soil{sensor_id}'],
                        mode='lines',
                        line=dict(shape='hvh')
                    ))
        
        # Add optimal moisture range
        fig.add_hrect(
            y0=300, y1=700,
            fillcolor="green", opacity=0.1,
            layer="below", line_width=0,
            annotation_text="Optimal",
            annotation_position="left"
        )
        
        # Update y-axis range based on actual data
        all_moisture_cols = [col for col in soil_df.columns if col.startswith('Moisture')]
        if all_moisture_cols:
            y_min = min(soil_df[col].min() for col in all_moisture_cols)
            y_max = max(soil_df[col].max() for col in all_moisture_cols)
            padding = (y_max - y_min) * 0.1
            y_range = [y_min - padding, y_max + padding]
        else:
            y_range = [0, 1000]
    
        # Apply optimized layout with dynamic y-range
        fig.update_layout(
            **create_optimized_figure_layout('Bodenfeuchtigkeit', 'Feuchtigkeit (raw)', y_range)
        )
    else:
        # Apply default layout if no data
        fig.update_layout(
            **create_optimized_figure_layout('Bodenfeuchtigkeit', 'Feuchtigkeit (raw)', [0, 1000])
        )
    
    return fig

def create_soil_temperature_figure(soil_df):
    """Create soil temperature plot with optimized layout."""
    fig = go.Figure()
    
    if not soil_df.empty:
        for sensor_id in [1, 2]:
            temp_col = f'Temperature{sensor_id}'
            if temp_col in soil_df.columns:
                # Convert temperature values to numeric, handling errors
                soil_df[temp_col] = pd.to_numeric(soil_df[temp_col], errors='coerce')
                
                # Remove NaN values
                valid_data = soil_df.dropna(subset=[temp_col, 'Timestamp'])
                
                if not valid_data.empty:
                    fig.add_trace(go.Scatter(
                        x=valid_data['Timestamp'],
                        y=valid_data[temp_col],
                        name=SENSOR_NAMES[f'soil{sensor_id}'],
                        mode='lines',
                        line=dict(shape='hvh')
                    ))
    
    # Add optimal temperature range
    fig.add_hrect(
        y0=20, y1=28,
        fillcolor="green", opacity=0.1,
        layer="below", line_width=0,
        annotation_text="Optimal",
        annotation_position="left"
    )
    
    # Apply optimized layout
    fig.update_layout(
        **create_optimized_figure_layout('Bodentemperatur', 'Temperatur (°C)', [15, 30])
    )
    
    return fig

def create_ventilation_power_figure(power_df):
    """Create ventilation power figure with optimized layout."""
    fig = go.Figure()
    
    try:
        if not power_df.empty and 'Timestamp' in power_df.columns and 'PowerPercentage' in power_df.columns:
            # Debug information
            print(f"Creating power figure with {len(power_df)} data points")
            if len(power_df) > 0:
                print(f"Time range: {power_df['Timestamp'].min()} to {power_df['Timestamp'].max()}")
                print(f"Power range: {power_df['PowerPercentage'].min():.1f}% to {power_df['PowerPercentage'].max():.1f}%")
            
            # Ensure PowerPercentage values are numeric
            power_df['PowerPercentage'] = pd.to_numeric(power_df['PowerPercentage'], errors='coerce')
            
            # Remove any NaN values
            valid_data = power_df.dropna(subset=['Timestamp', 'PowerPercentage'])
            
            if not valid_data.empty:
                fig.add_trace(go.Scatter(
                    x=valid_data['Timestamp'],
                    y=valid_data['PowerPercentage'],
                    mode='lines',
                    name='Fan Power',
                    line=dict(shape='hvh')
                ))
                
                # Add optimal power range
                fig.add_hrect(
                    y0=15, y1=85,
                    fillcolor="green", opacity=0.1,
                    layer="below", line_width=0,
                    annotation_text="Optimal",
                    annotation_position="left"
                )
            else:
                print("No valid power data after removing NaN values")
        else:
            print("No valid power data available for plotting")
    
    except Exception as e:
        print(f"Error creating power figure: {e}")
        print(traceback.format_exc())
    
    # Apply optimized layout
    fig.update_layout(
        **create_optimized_figure_layout('Lüftungs Leistung', 'Leistung (%)', [0, 100])
    )
    
    return fig

def _create_detailed_stats_cards(stats):
    """Create statistics cards with a simplified, compact design"""
    stats_cards = []
    
    def _is_dict_empty(d):
        """Check if dictionary is empty or contains only empty values"""
        if not isinstance(d, dict):
            return True
        return not bool(d) or all(not v for v in d.values())
    
    def _create_section_stats(title, section_data):
        """Create a compact stats card for a section"""
        if title == 'Raum' and isinstance(section_data, dict):
            section_data = {'Raum': section_data}
        
        if not section_data or not isinstance(section_data, dict):
            return None
        
        section_sections = []
        
        # Prioritize Austritt and Eintritt sections
        ordered_subsections = []
        for subsection, subsection_stats in section_data.items():
            if subsection == 'Austritt':
                ordered_subsections.insert(0, (subsection, subsection_stats))
            elif subsection == 'Eintritt':
                ordered_subsections.append((subsection, subsection_stats))
            elif subsection != 'Boden':
                ordered_subsections.append((subsection, subsection_stats))
        
        # Add Boden last if it exists
        if 'Boden' in section_data:
            ordered_subsections.append(('Boden', section_data['Boden']))
        
        for subsection, subsection_stats in ordered_subsections:
            if not _is_dict_empty(subsection_stats):
                subsection_content = []
                
                for category, category_stats in subsection_stats.items():
                    stat_rows = []
                    for k, v in category_stats.items():
                        stat_rows.append(
                            html.Div([
                                html.Span(
                                    k.replace('Temperatur', '').replace('Luftfeuchtigkeit', '').strip(), 
                                    style={
                                        'color': 'var(--text-secondary)', 
                                        'fontSize': '0.7rem',
                                        'width': '50%'
                                    }
                                ),
                                html.Span(
                                    v, 
                                    style={
                                        'color': 'var(--accent)',
                                        'fontWeight': 'bold',
                                        'fontSize': '0.7rem',
                                        'width': '50%',
                                        'textAlign': 'right'
                                    }
                                )
                            ], style={
                                'display': 'flex', 
                                'justifyContent': 'space-between',
                                'padding': '0.2rem 0',
                                'borderBottom': '1px solid var(--border)'
                            })
                        )
                    
                    subsection_content.append(
                        html.Div([
                            html.H5(
                                category, 
                                style={
                                    'color': 'var(--text-primary)', 
                                    'fontSize': '0.8rem',
                                    'marginBottom': '0.3rem',
                                    'textAlign': 'center'
                                }
                            ),
                            html.Div(stat_rows)
                        ], style={
                            'backgroundColor': 'var(--bg-primary)',
                            'borderRadius': '4px',
                            'padding': '0.3rem',
                            'marginBottom': '0.3rem'
                        })
                    )
                
                section_sections.append(
                    html.Div([
                        html.H4(
                            subsection, 
                            style={
                                'color': 'var(--text-primary)', 
                                'fontSize': '0.9rem',
                                'marginBottom': '0.3rem',
                                'textAlign': 'center',
                                'paddingBottom': '0.2rem'
                            }
                        )
                    ] + subsection_content, style={
                        'marginBottom': '0.3rem'
                    })
                )
        
        if not section_sections:
            return None
        
        return html.Div([
            html.H3(
                title, 
                style={
                    'color': 'var(--accent)', 
                    'fontSize': '1rem',
                    'marginBottom': '0.5rem', 
                    'textAlign': 'center',
                    'paddingBottom': '0.2rem'
                }
            ),
            html.Div(section_sections)
        ], className='stats-card')
    
    # Create stats card for each main section
    for section_name, section_data in stats.items():
        section_card = _create_section_stats(section_name, section_data)
        if section_card:
            stats_cards.append(section_card)
    
    return stats_cards

# Set App Layout
app.layout = html.Div([
    # Store components (unchanged)
    dcc.Store(id='valve-1-state', data=False),
    dcc.Store(id='valve-2-state', data=False),
    dcc.Store(id='valve-1-timer-state', data=None),
    dcc.Store(id='valve-2-timer-state', data=None),
    
    # Main Grid Container
    html.Div([
        # Left Column - Controls
        html.Div([
            # Header Section
            html.Div([
                html.H1("Grow Monitor", 
                    style={
                        'color': 'var(--accent)', 
                        'fontSize': '1.1rem',
                        'marginBottom': '0.01rem',
                        'textAlign': 'center'
                    }),
                html.Div([
                    html.Span("Last Update: ", 
                        style={
                            'color': 'var(--text-primary)', 
                            'fontWeight': 'bold', 
                            'fontSize': '0.8rem'
                        }),
                    html.Span(
                        id='last-update-time', 
                        children=datetime.now().strftime("%H:%M:%S"),
                        style={
                            'color': 'var(--text-secondary)', 
                            'marginLeft': '0.1rem',
                            'fontSize': '0.8rem'
                        })
                ], style={'textAlign': 'center'})
            ], style={'marginBottom': '0.001rem'}),
            
            # Control Panel (with responsive classes)
            html.Div(create_unified_control_panel(), className='mobile-padding'),
            
            # File Selectors (with responsive classes)
            html.Div(create_file_selectors(), className='mobile-padding'),
        ], className='column-left'),
        
        # Middle Column - Monitoring and Graphs
        html.Div([
            # Scrollable content container
            html.Div([
                # Unified Monitoring Section
                create_unified_monitoring_section(),
                
                # Graphs Container
                html.Div([
                    dcc.Graph(id='ventilation-power-graph', className='responsive-graph'),
                    dcc.Graph(id='vpd-graph', className='responsive-graph'),
                    dcc.Graph(id='temperature-graph', className='responsive-graph'),
                    dcc.Graph(id='humidity-graph', className='responsive-graph'),
                    dcc.Graph(id='soil-temperature-graph', className='responsive-graph'),
                    dcc.Graph(id='soil-moisture-graph', className='responsive-graph')
                ], style={
                    'display': 'flex',
                    'flexDirection': 'column',
                    'gap': '0.5rem'
                })
            ], className='scrollable-content')
        ], className='column-middle'),
        
        # Right Column - Stats
        html.Div([
            html.Div([
                html.H2("Statistics Overview", style={
                    'color': 'var(--accent)',
                    'fontSize': '0.8rem',
                    'marginBottom': '0.2rem',
                    'textAlign': 'center',
                    'paddingBottom': '0.1rem'
                }),
                html.Div(id='stats-container', className='stats-container')
            ], className='scrollable-content')
        ], className='column-right hide-on-mobile')
        
    ], className='main-grid'),
    
    # Intervals
    dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0),
    dcc.Interval(id='timer-interval', interval=1000, n_intervals=0)
    
], className='dash-container')

# Index string with responsive CSS
app.index_string = '''
<!DOCTYPE html>
<html lang="de">
    <head>
        {%metas%}
        <title>Grow Monitor Dashboard</title>
        {%favicon%}
        {%css%}
        <style>
            :root {
                --bg-primary: #1a1a1a;
                --bg-secondary: #2d2d2d;
                --text-primary: #e0e0e0;
                --text-secondary: #b0b0b0;
                --accent: #4CAF50;
                --border: #404040;
                --success: #4CAF50;
                --warning: #FFC107;
                --error: #f44336;
            }

            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }

            body {
                background-color: var(--bg-primary);
                color: var(--text-primary);
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                line-height: 1.4;
                height: 100vh;
                width: 100vw;
                overflow-x: hidden;
            }

            /* Fluid Typography */
            html {
                font-size: 14px;
            }

            @media (min-width: 768px) {
                html {
                    font-size: 16px;
                }
            }

            /* Responsive container */
            .dash-container {
                width: 100%;
                max-width: 100vw;
                margin: 0 auto;
                padding: 0.4rem;
            }

            /* Main grid layout for responsive design */
            .main-grid {
                display: flex;
                flex-direction: column;
                gap: 0.4rem;
                height: auto;
                min-height: 100vh;
                width: 100%;
            }

            @media (min-width: 992px) {
                .main-grid {
                    flex-direction: row;
                }
            }

            /* Columns styles */
            .column-left, .column-middle, .column-right {
                width: 100%;
                margin-bottom: 0.5rem;
                background-color: var(--bg-secondary);
                border-radius: 8px;
                overflow: hidden;
            }

            @media (min-width: 992px) {
                .column-left {
                    width: 25%;
                    margin-bottom: 0;
                }
                
                .column-middle {
                    width: 65%;
                    margin-left: 0.4rem;
                    margin-bottom: 0;
                }
                
                .column-right {
                    width: 10%;
                    margin-left: 0.4rem;
                    margin-bottom: 0;
                }
            }

            /* Scrollable content */
            .scrollable-content {
                height: auto;
                max-height: 95vh;
                overflow-y: auto;
                padding: 0.2rem;
            }

            @media (min-width: 992px) {
                .scrollable-content {
                    height: 95vh;
                }
            }

            /* Image container */
            .image-container img {
                width: 100%;
                height: auto;
                max-width: 100%;
                object-fit: contain;
            }

            /* Camera section */
            .camera-grid {
                display: grid;
                grid-template-columns: 1fr;
                gap: 0.5rem;
            }

            @media (min-width: 768px) {
                .camera-grid {
                    grid-template-columns: repeat(2, 1fr);
                }
            }

            /* Gauge container for small screens */
            .gauge-container {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 0.05rem;
            }

            @media (min-width: 576px) {
                .gauge-container {
                    grid-template-columns: repeat(3, 1fr);
                }
            }

            @media (min-width: 768px) {
                .gauge-container {
                    grid-template-columns: repeat(4, 1fr);
                }
            }

            @media (min-width: 1200px) {
                .gauge-container {
                    grid-template-columns: repeat(auto-fit, minmax(60px, 1fr));
                }
            }
            
            

            /* Stats cards responsiveness */
            .stats-container {
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                align-items: flex-start;
                gap: 0.5rem;
            }

            .stats-card {
                width: 100%;
                max-width: 300px;
                margin: 0.2rem;
                background-color: var(--bg-secondary);
                border-radius: 6px;
                padding: 0.5rem;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            }

            @media (min-width: 576px) {
                .stats-card {
                    width: calc(50% - 0.4rem);
                }
            }

            @media (min-width: 992px) {
                .stats-card {
                    width: 100%;
                }
            }

            /* Touch-friendly controls */
            input, button, .Select-control {
                min-height: 36px;
            }

            /* Graph responsiveness */
            .responsive-graph {
                height: 250px;
                width: 100%;
            }

            @media (min-width: 768px) {
                .responsive-graph {
                    height: 300px;
                }
            }

            @media (min-width: 1200px) {
                .responsive-graph {
                    height: 350px;
                }
            }

            /* Control panel responsiveness */
            .control-panel-grid {
                display: grid;
                grid-template-columns: 1fr;
                gap: 0.5rem;
            }

            @media (min-width: 768px) {
                .control-panel-grid {
                    grid-template-columns: repeat(2, 1fr);
                }
            }
            
            /* Control panel section */
            .control-panel-section {
                flex: 1;
                margin-bottom: 0.5rem;
            }

            @media (min-width: 768px) {
                .control-panel-section {
                    margin-right: 0.5rem;
                    margin-bottom: 0;
                }
                
                .control-panel-section:last-child {
                    margin-right: 0;
                }
            }

            .control-item {
                background-color: var(--bg-primary);
                padding: 0.5rem;
                border-radius: 4px;
                margin-bottom: 0.5rem;
            }
            
            /* Selector styling */
            .selector-label {
                color: #e0e0e0;
                font-size: 0.7rem;
                margin-bottom: 0.1rem;
                display: block;
            }

            .selector-item {
                margin-bottom: 0.5rem;
            }

            /* Input style */
            .responsive-input {
                width: 70px;
                background-color: var(--bg-primary);
                color: var(--text-primary);
                border: 1px solid var(--border);
                border-radius: 4px;
                padding: 0.25rem;
                font-size: 0.8rem;
            }

            @media (max-width: 576px) {
                .responsive-input {
                    width: 60px;
                    font-size: 0.7rem;
                }
            }

            /* Time range radio responsive styling */
            .time-range-radio {
                display: flex;
                flex-wrap: wrap;
                gap: 0.3rem;
                margin-top: 0.1rem;
            }

            /* Hide elements on very small screens */
            @media (max-width: 480px) {
                .hide-on-mobile {
                    display: none !important;
                }
            }

            /* Custom dropdown for small screens */
            .custom-dropdown .Select-control {
                height: 36px !important;
            }

            .custom-dropdown .Select-input {
                height: 34px !important;
            }

            .custom-dropdown .Select-placeholder, 
            .custom-dropdown .Select-value {
                line-height: 34px !important;
            }

            /* Consistent padding on mobile */
            .mobile-padding {
                padding: 0.3rem !important;
            }

            /* Stack elements on smaller screens */
            .flex-stack {
                display: flex;
                flex-direction: column;
            }

            @media (min-width: 768px) {
                .flex-stack {
                    flex-direction: row;
                }
            }
            
            /* Gauge item responsiveness */
            .gauge-item {
                width: 100%;
                margin-bottom: 0.25rem;
            }

            @media (max-width: 576px) {
                .gauge-container {
                    padding: 0.03rem;
                }
                
                .gauge-label {
                    font-size: 0.7rem !important;
                }
            }
            
            /* Media query for very small screens */
            @media (max-width: 320px) {
                .time-range-radio {
                    flex-direction: column;
                }
            }

            /* Make sure plots are visible on all screen sizes */
            .js-plotly-plot {
                width: 100% !important;
            }

            .main-svg, .svg-container {
                width: 100% !important;
            }

            /* Add optimizations for touch devices */
            @media (pointer: coarse) {
                /* Larger touch targets */
                input, button, .Select-control, .radio-item label, .toggle-switch {
                    min-height: 44px;
                }
                
                /* More space between items */
                .selector-item, .control-item {
                    margin-bottom: 0.8rem;
                }
            }

            /* Orientation changes */
            @media screen and (orientation: portrait) {
                .main-grid {
                    flex-direction: column;
                }
                
                .column-left, .column-middle {
                    width: 100%;
                }
                
                .column-right {
                    display: none;
                }
            }

            @media screen and (orientation: landscape) and (min-width: 992px) {
                .main-grid {
                    flex-direction: row;
                }
                
                .column-left {
                    width: 25%;
                }
                
                .column-middle {
                    width: 65%;
                }
                
                .column-right {
                    width: 10%;
                    display: block;
                }
            }

            /* Media query for small height screens */
            @media (max-height: 600px) {
                .scrollable-content {
                    max-height: 85vh;
                }
                
                .responsive-graph {
                    height: 200px;
                }
            }

            /* Scrollbar Styling */
            ::-webkit-scrollbar {
                width: 6px;
                height: 6px;
            }

            ::-webkit-scrollbar-track {
                background: var(--bg-primary);
            }

            ::-webkit-scrollbar-thumb {
                background: var(--border);
                border-radius: 4px;
            }

            ::-webkit-scrollbar-thumb:hover {
                background: var(--accent);
            }

            /* Stats Box Styling */
            .stats-box {
                background-color: var(--bg-primary);
                border-radius: 4px;
                padding: 0.3rem;
                margin-bottom: 0.3rem;
            }

            .stats-box h3 {
                color: var(--accent);
                font-size: 0.8rem;
                margin-bottom: 0.2rem;
                border-bottom: 1px solid var(--border);
                padding-bottom: 0.1rem;
                text-align: center;
            }

            .stats-box .stats-content {
                display: flex;
                flex-direction: column;
                gap: 0.2rem;
            }

            .stats-box .stat-item {
                display: flex;
                justify-content: space-between;
                font-size: 0.7rem;
                padding: 0.1rem 0;
                border-bottom: 1px solid var(--border);
            }

            .stats-box .stat-label {
                color: var(--text-secondary);
                width: 50%;
            }

            .stats-box .stat-value {
                color: var(--accent);
                font-weight: bold;
                width: 50%;
                text-align: right;
            }

            /* Input & Button Styling */
            input {
                background-color: var(--bg-primary);
                color: var(--text-primary);
                border: 1px solid var(--border);
                border-radius: 4px;
                padding: 0.2rem 0.4rem;
                font-size: 0.8rem;
            }

            input:focus {
                outline: none;
                border-color: var(--accent);
            }

            /* Updated Gauge Container Styles */
            .gauge-container {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(60px, 1fr));
                gap: 0.05rem;
                padding: 0.05rem;
                background-color: var(--bg-secondary);
                border-radius: 0.1rem;
                margin-bottom: 0.05rem;
                max-width: 100%; /* Ensure it doesn't overflow */
            }
            
            .gauge-value {
                color: var(--accent);
                font-size: 0.8rem;
                font-weight: bold;
                margin-top: 0.9rem;
            }

            .monitoring-section {
                background-color: var(--bg-secondary);
                border-radius: 0.1rem;
                padding: 0.05rem;
                margin-bottom: 0.05rem;
            }

            /* Modify the sections containing gauges */
            .monitoring-section > div {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 0.2rem;
                margin-bottom: 0.2rem;
            }

            .monitoring-section .section-header {
                font-size: 0.7rem;
                margin-bottom: 0.05rem;
                padding-bottom: 0.05rem;
            }

            /* Adjust the overall layout to reduce spacing */
            .middle-column {
                gap: 0.5rem;
            }
            
            /* Camera Section */
            .camera-section {
                background-color: var(--bg-secondary);
                border-radius: 8px;
                padding: 0.5rem;
                margin-bottom: 0.5rem;
            }

            .camera-card {
                background-color: var(--bg-primary);
                border-radius: 6px;
                overflow: hidden;
            }

            .camera-card img {
                width: 100%;
                height: auto;
                display: block;
            }

            /* Ventilation Controls */
            .ventilation-controls {
                background-color: var(--bg-primary);
                border-radius: 6px;
                padding: 0.5rem;
                margin-bottom: 0.5rem;
            }

            .ventilation-slider {
                padding: 0.4rem 0;
            }

            .ventilation-status {
                font-size: 0.75rem;
                color: var(--text-secondary);
                margin-top: 0.2rem;
            }

            .ventilation-controls-item {
                margin-bottom: 0.5rem;
            }

            /* Responsive Adjustments */
            @media screen and (max-width: 1600px) {
                .graph-container {
                    padding: 0.4rem;
                }
                
                input, button {
                    padding: 0.2rem 0.4rem;
                }
                
                .Select-control {
                    height: 26px !important;
                }
            }

            /* Graph and Plotly Adjustments */
            .js-plotly-plot {
                margin-bottom: 0 !important;
            }

            .js-plotly-plot .plotly .modebar {
                top: 0 !important;
            }

            /* Cannabis icon styling */
            .cannabis-icon {
                z-index: 1000;
                transition: all 0.3s ease;
                position: fixed;
                top: -35px;
                left: 0px;
                width: 240px;
                height: 240px;
                opacity: 0.8;
                pointer-events: none;
            }

            @media (max-width: 768px) {
                .cannabis-icon {
                    width: 120px;
                    height: 120px;
                    top: -18px;
                    left: 0px;
                }
            }

            @media (max-width: 480px) {
                .cannabis-icon {
                    width: 80px;
                    height: 80px;
                    top: -10px;
                    left: 0px;
                }
            }
            
            /* More compact control panel and sensor displays */
            .control-item {
                background-color: var(--bg-primary);
                padding: 0.3rem;
                border-radius: 4px;
                margin-bottom: 0.3rem;
            }

            .monitoring-section {
                background-color: var(--bg-secondary);
                border-radius: 0.1rem;
                padding: 0.03rem;
                margin-bottom: 0.03rem;
            }

            .gauge-container {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(50px, 1fr));
                gap: 0.03rem;
                padding: 0.03rem;
            }

            .gauge-item {
                width: 100%;
                margin-bottom: 0.1rem;
            }

            .gauge-label {
                font-size: 0.65rem !important;
            }

            .gauge-value {
                font-size: 0.65rem !important;
            }
            
            /* Improved gauge container styles for horizontal layout */
            .gauge-group {
                background-color: var(--bg-primary);
                border-radius: 4px;
                padding: 0.3rem;
                margin-bottom: 0.4rem;
            }

            .gauge-row {
                display: flex;
                flex-direction: row;
                flex-wrap: wrap;
                justify-content: space-around;
                gap: 0.2rem;
            }

            .gauge-item {
                flex: 1;
                min-width: 80px;
                max-width: 150px;
                margin-bottom: 0.1rem;
                padding: 0.1rem;
                background-color: var(--bg-secondary);
                border-radius: 3px;
            }

            /* Ensure gauge containers use available space optimally */
            .monitoring-section {
                background-color: var(--bg-secondary);
                border-radius: 6px;
                padding: 0.4rem;
                margin-bottom: 0.5rem;
            }

            /* Adjust for smaller screens */
            @media (max-width: 768px) {
                .gauge-row {
                    flex-direction: row;
                }
                
                .gauge-item {
                    min-width: 70px;
                    padding: 0.1rem;
                }
            }

            /* For very small screens, allow stacking if needed */
            @media (max-width: 480px) {
                .gauge-row {
                    flex-wrap: wrap;
                }
                
                .gauge-item {
                    min-width: 65px;
                    flex-basis: calc(50% - 0.2rem);
                }
            }

            /* Ensure the graphs don't get too compressed */
            .js-plotly-plot .main-svg {
                min-height: 70px !important;
            }

            /* More compact spacing for gauge items */
            .gauge-item .gauge-label, .gauge-item .gauge-value {
                font-size: 0.7rem !important;
                margin: 0;
                padding: 0;
            }            

            /* Increased graph size for mobile devices */
            @media (max-width: 768px) {
                .responsive-graph {
                    height: 300px;
                }
                
                /* Make control panel more compact */
                .control-panel-grid {
                    gap: 0.2rem;
                }
                
                .control-panel-section {
                    margin-bottom: 0.2rem;
                }
                
                /* Adjust main layout to give more space to graphs */
                .column-middle {
                    width: 100%;
                }
                
                /* Further reduce spacing in monitoring section */
                .monitoring-section > div {
                    gap: 0.1rem;
                    margin-bottom: 0.1rem;
                }
                
                /* Reduce size of gauge graphs */
                .js-plotly-plot .main-svg {
                    height: 70px !important;
                }
                
                /* Make gauge containers more compact for very small screens */
                @media (max-width: 480px) {
                    .gauge-container {
                        grid-template-columns: repeat(3, 1fr);
                    }
                }
            }

            /* Improved layout for tablets and small laptops */
            @media (min-width: 769px) and (max-width: 1200px) {
                .responsive-graph {
                    height: 320px;
                }
                
                .gauge-container {
                    grid-template-columns: repeat(4, 1fr);
                }
            }

            /* Adjust graph container spacing to maximize graph space */
            .graph-container {
                padding: 0.2rem;
            }

            /* More vertical space for graphs on mobile */
            @media (max-width: 768px) {
                .scrollable-content {
                    padding-top: 0.1rem;
                    padding-bottom: 0.1rem;
                }
                
                /* Stack graphs with minimal spacing between them */
                .responsive-graph {
                    margin-bottom: 0.2rem;
                }
            }

            /* Allow graphs to fill available space */
            .js-plotly-plot, .svg-container, .plot-container {
                width: 100% !important;
            }

            /* Adjust padding for mobile */
            .mobile-padding {
                padding: 0.2rem !important;
            }

            /* Further optimize for small height screens */
            @media (max-height: 600px) {
                .responsive-graph {
                    height: 250px;
                }
                
                .gauge-item {
                    margin-bottom: 0.05rem;
                }
            }
            
            /* Button Improvements */
            .dash-daq-powerbutton {
                min-width: 32px !important;
                min-height: 32px !important;
                max-width: 32px !important;
                max-height: 32px !important;
                border-radius: 50% !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4) !important;
                padding: 0 !important;
                margin: 2px !important;
            }

            .dash-daq-booleanswitch {
                max-width: 36px !important;
                min-width: 36px !important;
                height: 18px !important;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3) !important;
            }

            /* Make all DAQ components more compact */
            .dash-daq input {
                margin: 0 !important;
                padding: 2px 4px !important;
                height: 30px !important;
            }

            /* More compact control panel for mobile */
            @media (max-width: 768px) {
                /* Smaller section titles */
                .control-panel-section h3 {
                    font-size: 1rem !important;
                    margin-bottom: 0.2rem !important;
                    padding: 0.2rem !important;
                }
                
                .control-panel-section h4 {
                    font-size: 0.85rem !important;
                    margin-bottom: 0.1rem !important;
                }
                
                /* Smaller spacing in control items */
                .control-item {
                    padding: 0.2rem !important;
                    margin-bottom: 0.2rem !important;
                }
                
                /* Make input fields smaller */
                .responsive-input {
                    width: 60px !important;
                    height: 26px !important;
                    padding: 1px 4px !important;
                    font-size: 0.7rem !important;
                }
                
                /* Tighter flex stacks */
                .flex-stack {
                    gap: 0.2rem !important;
                    margin-bottom: 0.2rem !important;
                }
                
                /* Tighter layouts for ventilation control */
                .ventilation-controls-item {
                    margin-bottom: 0.2rem !important;
                }
                
                /* Make the slider more compact */
                .ventilation-slider {
                    padding: 0.1rem 0 !important;
                    height: 26px !important;
                }
                
                /* Reduce height of dropdowns */
                .custom-dropdown .Select-control {
                    height: 26px !important;
                    min-height: 26px !important;
                }
                
                .custom-dropdown .Select-input {
                    height: 24px !important;
                }
                
                .custom-dropdown .Select-placeholder,
                .custom-dropdown .Select-value {
                    line-height: 24px !important;
                    padding-left: 6px !important;
                    font-size: 0.7rem !important;
                }
                
                /* Labels */
                .selector-label, .control-item label {
                    font-size: 0.7rem !important;
                    margin-bottom: 0.05rem !important;
                }
                
                /* Create more compact button groups */
                .flex-stack {
                    display: flex;
                    flex-wrap: wrap;
                    align-items: center;
                }
                
                /* Make column spacing tighter */
                .control-panel-grid {
                    gap: 0.2rem !important;
                }
                
                /* More compact radio buttons */
                .time-range-radio {
                    gap: 0.1rem !important;
                }
                
                .time-range-radio label {
                    font-size: 0.7rem !important;
                    padding: 0.1rem !important;
                }
                
                /* Tighter padding in main container */
                .mobile-padding {
                    padding: 0.15rem !important;
                }
            }

            /* Further optimizations for very small screens */
            @media (max-width: 480px) {
                /* Even smaller fonts */
                .control-panel-section h3 {
                    font-size: 0.9rem !important;
                }
                
                .control-panel-section h4 {
                    font-size: 0.8rem !important;
                }

                /* Ultra-compact layout */
                .control-item {
                    padding: 0.15rem !important;
                    margin-bottom: 0.15rem !important;
                }
                
                /* Ensure input fields fit properly */
                .responsive-input {
                    width: 50px !important;
                    font-size: 0.65rem !important;
                }
                
                /* Better alignment for power buttons */
                .dash-daq-powerbutton {
                    min-width: 28px !important;
                    min-height: 28px !important;
                    max-width: 28px !important;
                    max-height: 28px !important;
                }
                
                /* Make ventilation control more compact */
                .ventilation-status {
                    font-size: 0.65rem !important;
                }
                
                /* Special handling for very tiny screens */
                @media (max-width: 350px) {
                    .control-panel-grid {
                        display: flex !important;
                        flex-direction: column !important;
                    }
                    
                    .responsive-input {
                        width: 45px !important;
                    }
                }
            }

            /* Improved Button Styling */
            daq-powerbutton {
                position: relative !important;
                overflow: visible !important;
            }

            daq-powerbutton:after {
                content: "" !important;
                position: absolute !important;
                top: -2px !important;
                left: -2px !important;
                right: -2px !important;
                bottom: -2px !important;
                border-radius: 50% !important;
                border: 1px solid var(--border) !important;
                pointer-events: none !important;
            }

            /* Custom styling for boolean switches */
            .dash-daq-booleanswitch:after {
                content: "" !important;
                position: absolute !important;
                top: -1px !important;
                left: -1px !important;
                right: -1px !important;
                bottom: -1px !important;
                border-radius: 10px !important;
                border: 1px solid var(--border) !important;
                pointer-events: none !important;
            }

            /* Better touch targets with visual clarity */
            .flex-stack .dash-daq-powerbutton,
            .flex-stack .dash-daq-booleanswitch {
                margin-left: 4px !important;
                margin-right: 4px !important;
            }

            /* Create better structured form controls */
            .form-row {
                display: flex;
                flex-wrap: wrap;
                align-items: center;
                margin-bottom: 0.2rem;
                gap: 0.2rem;
            }

            .form-row label {
                flex: 0 0 auto;
                margin-right: 0.3rem;
            }

            .form-row input, 
            .form-row .dash-daq-booleanswitch,
            .form-row .dash-daq-powerbutton {
                flex: 0 0 auto;
            }

            /* Compact vertical layout for certain controls */
            .compact-controls {
                display: flex;
                flex-direction: column;
                gap: 0.15rem;
            }
            
            /* File selector improvements */
            .file-selector-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 0.2rem;
            }

            .time-selector {
                grid-column: span 2;
            }

            /* For larger screens, use 4 columns */
            @media (min-width: 768px) {
                .file-selector-grid {
                    grid-template-columns: 1fr 1fr 1fr 1fr;
                }
                
                .time-selector {
                    grid-column: span 1;
                }
            }

            /* Better dropdown styling for mobile */
            .custom-dropdown {
                font-size: 0.7rem;
            }

            .custom-dropdown .Select-menu-outer {
                max-height: 200px;
                font-size: 0.7rem;
            }

            .custom-dropdown .Select-option {
                padding: 4px 8px;
            }

            /* Improved time range radio styling */
            .time-range-radio {
                display: flex;
                justify-content: space-evenly;
                flex-wrap: wrap;
            }

            .time-range-radio label {
                background-color: var(--bg-primary);
                border-radius: 3px;
                padding: 2px 4px;
                margin: 2px;
                font-size: 0.7rem;
                text-align: center;
            }

            .time-range-radio input:checked + span {
                color: var(--accent);
                font-weight: bold;
            }

            /* Form row improvements */
            .form-row {
                display: flex;
                align-items: center;
                margin-bottom: 0.15rem;
                padding: 0.05rem;
                border-radius: 3px;
            }

            .form-row:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }

            /* Button tweaks to ensure they don't appear blobby */
            .dash-daq-powerbutton > div, 
            .dash-daq-booleanswitch > div {
                border-radius: 50% !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3) !important;
            }

            /* Make sure the power button's circle appears properly */
            .dash-daq-powerbutton > div > div {
                border-radius: 50% !important;
            }

            /* Boolean switch track fix */
            .dash-daq-booleanswitch > div > div:first-child {
                border-radius: 10px !important;
            }

            /* Boolean switch handle */
            .dash-daq-booleanswitch > div > div:nth-child(2) {
                border-radius: 50% !important;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.5) !important;
            }

            /* Input field improvements */
            .responsive-input {
                background-color: var(--bg-primary);
                color: var(--text-primary);
                border: 1px solid var(--border);
                border-radius: 3px;
                font-size: 0.75rem;
                height: 28px;
            }

            .responsive-input:focus {
                border-color: var(--accent);
                outline: none;
                box-shadow: 0 0 0 1px var(--accent);
            }

            /* Slider handle and track improvements */
            .rc-slider-handle {
                border-color: var(--accent) !important;
                background-color: var(--accent) !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3) !important;
                width: 14px !important;
                height: 14px !important;
                margin-top: -5px !important;
            }

            .rc-slider-track {
                background-color: var(--accent) !important;
            }

            .rc-slider-rail {
                background-color: var(--bg-primary) !important;
            }

            /* Make control items more distinct */
            .control-item {
                background-color: var(--bg-primary);
                border-radius: 4px;
                padding: 0.3rem;
                margin-bottom: 0.3rem;
                border: 1px solid rgba(255, 255, 255, 0.05);
            }

            .control-item:hover {
                border-color: rgba(255, 255, 255, 0.1);
            }

            /* Better mobile padding for entire app */
            @media (max-width: 768px) {
                .dash-container {
                    padding: 0.2rem;
                }
                
                .column-left, .column-middle, .column-right {
                    margin-bottom: 0.2rem;
                    border-radius: 6px;
                }
                
                .main-grid {
                    gap: 0.2rem;
                }
                
                /* Make the main content area use more space */
                .scrollable-content {
                    padding: 0.1rem;
                }
                
                /* Even smaller margins between controls */
                .control-panel-grid {
                    gap: 0.15rem;
                }
                
                /* Better alignment for timer displays */
                [id$="-timer"] {
                    min-height: 1rem;
                    font-size: 0.65rem !important;
                }
                
                /* Better alignment for schedule status */
                [id$="-schedule-status"] {
                    min-height: 1rem;
                    font-size: 0.65rem !important;
                }
                
                /* More compact ventilation controls */
                .ventilation-controls {
                    padding: 0.2rem;
                }
                
                .ventilation-status {
                    font-size: 0.65rem !important;
                    line-height: 1.2;
                }
                
                /* Better label spacing */
                label {
                    margin-bottom: 0 !important;
                }
            }

            /* Ultra compact for very small screens */
            @media (max-width: 320px) {
                .control-panel-grid {
                    display: block;
                }
                
                .control-panel-section {
                    margin-bottom: 0.2rem;
                }
            }

            /* Better vertical alignment of form elements */
            .form-row > * {
                vertical-align: middle;
            }

            /* Improved dropdown menu appearance */
            .Select-menu-outer {
                background-color: var(--bg-secondary) !important;
                border: 1px solid var(--border) !important;
            }

            .Select-option {
                background-color: var(--bg-secondary) !important;
                color: var(--text-primary) !important;
            }

            .Select-option:hover,
            .Select-option.is-focused {
                background-color: var(--bg-primary) !important;
            }

            .Select-value-label {
                color: var(--text-primary) !important;
            }

            /* Main layout optimization */
            .main-grid {
                min-height: 0;
            }

            /* Remove unused whitespace in camera section */
            #camera-images-container {
                margin-bottom: 0.5rem !important;
            }

            /* Make graph containers visually distinct */
            .responsive-graph {
                background-color: var(--bg-secondary);
                border-radius: 4px;
                padding: 0.2rem;
            }

            /* Better spacing for ventilation slider */
            .ventilation-slider {
                margin: 0.2rem 0.4rem;
            }

            /* Improved appearance when focusing on form elements */
            .form-row:focus-within {
                background-color: rgba(255, 255, 255, 0.07);
            } 
            
            /* Core graph container improvements */
            .responsive-graph {
                height: auto !important;
                min-height: 220px;
                margin-bottom: 0.5rem;
                width: 100%;
                background-color: var(--bg-primary);
                border-radius: 4px;
                overflow: hidden;
                box-sizing: border-box;
            }

            /* Make Plotly use all available space */
            .js-plotly-plot {
                width: 100% !important;
                height: 100% !important;
            }

            .js-plotly-plot .plot-container {
                width: 100% !important;
                height: 100% !important;
            }

            /* Reduce margins and padding within plots */
            .js-plotly-plot .main-svg {
                width: 100% !important;
                height: 100% !important;
            }

            /* Move modebar to bottom right to avoid overlapping with title */
            .js-plotly-plot .modebar {
                top: auto !important;
                bottom: 0 !important;
                right: 0 !important;
            }

            /* Responsive graph height adjustments */
            @media (max-width: 1200px) {
                .responsive-graph {
                    min-height: 200px;
                }
            }

            @media (max-width: 768px) {
                .responsive-graph {
                    min-height: 180px;
                }
                
                /* More compact graph layout on mobile */
                .js-plotly-plot .main-svg {
                    /* Reduce top margin to save vertical space */
                    transform: translateY(-5px);
                }
                
                /* Compact graph spacing */
                .middle-column > div {
                    gap: 0.3rem !important;
                }
            }

            @media (max-width: 480px) {
                .responsive-graph {
                    min-height: 160px;
                    margin-bottom: 0.3rem;
                }
                
                /* Even more compact spacing on very small screens */
                .middle-column > div {
                    gap: 0.2rem !important;
                }
            }

            /* Optimize graph titles and labels for mobile */
            @media (max-width: 768px) {
                /* Make titles more compact */
                .gtitle {
                    font-size: 0.9rem !important;
                }
                
                /* Smaller axis titles */
                .g-xtitle, .g-ytitle {
                    font-size: 0.7rem !important;
                }
                
                /* Smaller tick labels */
                .xtick text, .ytick text {
                    font-size: 0.6rem !important;
                }
                
                /* Reduced legend size */
                .legend text {
                    font-size: 0.7rem !important;
                }
            }

            /* Make sure graphs take up full width */
            .js-plotly-plot, .plot-container, .svg-container {
                width: 100% !important;
            }

            /* Create a more efficient layout for graph container on mobile */
            @media (max-width: 768px) {
                /* Adjust the middle column to give more space to graphs */
                .column-middle {
                    padding: 0.1rem;
                }
                
                /* Ensure scrollable content uses maximum space */
                .scrollable-content {
                    padding: 0.1rem;
                    max-height: none;
                }
                
                /* Reorganize main grid to give more space to middle column */
                .main-grid {
                    display: grid;
                    grid-template-areas:
                        "left"
                        "middle";
                    grid-template-rows: auto 1fr;
                    grid-template-columns: 1fr;
                }
                
                .column-left {
                    grid-area: left;
                }
                
                .column-middle {
                    grid-area: middle;
                }
                
                /* Hide right column on mobile */
                .column-right {
                    display: none;
                }
            } 
            
            /* Reduce overall control panel size */
            .control-panel {
                max-width: 100%;
            }

            /* Smaller section headers */
            .control-panel h2 {
                font-size: 0.8rem !important;
                margin-bottom: 0.2rem !important;
                padding: 0 !important;
            }

            .control-panel h3 {
                font-size: 0.8rem !important;
                margin-bottom: 0.1rem !important;
                padding: 0 !important;
                border-bottom: 1px solid var(--border);
            }

            .control-panel h4 {
                font-size: 0.7rem !important;
                margin-bottom: 0.1rem !important;
                padding: 0 !important;
            }

            /* More compact control items */
            .control-item {
                padding: 0.15rem !important;
                margin-bottom: 0.15rem !important;
                border-radius: 3px;
            }

            /* Tighter form rows */
            .form-row {
                margin-bottom: 0.1rem !important;
                min-height: 24px !important;
            }

            /* More compact inputs */
            .responsive-input {
                width: 50px !important;
                height: 22px !important;
                padding: 1px 4px !important;
                font-size: 0.65rem !important;
                margin: 0 !important;
            }

            /* Smaller, more compact buttons */
            .dash-daq-powerbutton {
                min-width: 22px !important;
                min-height: 22px !important;
                max-width: 22px !important;
                max-height: 22px !important;
                margin: 0 !important;
            }

            .dash-daq-booleanswitch {
                max-width: 28px !important;
                min-width: 28px !important;
                height: 14px !important;
            }

            /* Condensed padding in all control sections */
            .mobile-padding {
                padding: 0.1rem !important;
            }

            /* Smaller labels */
            .control-panel label, .selector-label {
                font-size: 0.65rem !important;
                margin-bottom: 0 !important;
            }

            /* Smaller status text */
            [id$="-timer"], 
            [id$="-schedule-status"],
            .ventilation-status {
                font-size: 0.6rem !important;
                line-height: 1.1 !important;
                min-height: 12px !important;
                margin-top: 0 !important;
                margin-bottom: 0 !important;
            }

            /* More compact grid layout */
            .control-panel-grid {
                gap: 0.1rem !important;
                margin-bottom: 0.1rem !important;
            }

            /* Tighten up ventilation controls */
            .ventilation-controls {
                padding: 0.1rem !important;
            }

            .ventilation-controls-item {
                margin-bottom: 0.1rem !important;
            }

            .ventilation-slider {
                padding: 0 !important;
                margin: 0.1rem 0.2rem !important;
                height: 20px !important;
            }

            /* Smaller dropdown size */
            .custom-dropdown .Select-control {
                height: 22px !important;
                min-height: 22px !important;
            }

            .custom-dropdown .Select-input {
                height: 20px !important;
            }

            .custom-dropdown .Select-placeholder,
            .custom-dropdown .Select-value {
                line-height: 20px !important;
                padding-left: 4px !important;
                font-size: 0.65rem !important;
            }

            .custom-dropdown .Select-arrow-zone {
                padding-right: 4px !important;
            }

            /* Tighten up the file selector area */
            .file-selector-grid {
                gap: 0.1rem !important;
            }

            .selector-item {
                margin-bottom: 0.1rem !important;
            }

            /* Make the time radio more compact */
            .time-range-radio {
                margin-top: 0 !important;
            }

            .time-range-radio label {
                font-size: 0.65rem !important;
                padding: 1px 2px !important;
                margin: 1px !important;
            }

            /* More compact layout for the left column */
            .column-left {
                padding: 0.1rem !important;
            }

            /* Adjust overall layout proportions */
            @media (min-width: 992px) {
                .column-left {
                    width: 20% !important; /* Make it narrower */
                }
                
                .column-middle {
                    width: 70% !important; /* Give more space to graphs */
                }
            }

            /* Target only desktop with ultra-compact controls */
            @media (min-width: 768px) {
                /* Even more compact control panel on desktop */
                .control-panel-section, .control-item {
                    padding: 0.1rem !important;
                }
            }

            /* Additional spacing adjustments */
            .compact-controls > div:not(:last-child) {
                margin-bottom: 0.1rem !important;
            }

            /* Remove extra spacing in dropdown menu */
            .Select-menu-outer {
                margin-top: -1px !important;
            }

            .Select-menu {
                max-height: 150px !important;
            }

            /* More compact column spacing */
            .main-grid {
                gap: 0.15rem !important;
            }

            /* Remove unnecessary margins and padding */
            body, html {
                margin: 0 !important;
                padding: 0 !important;
            }

            .dash-container {
                padding: 0.15rem !important;
            } 

            /* Optimizing the balance between control panel and graphs */
            @media (min-width: 992px) {
                .column-left {
                    width: 18% !important; /* Even smaller control panel */
                }
                
                .column-middle {
                    width: 72% !important; /* More space for graphs */
                }
                
                .column-right {
                    width: 10%;
                }
            }

            /* Optimize layout for dashboard header */
            .dash-container h1 {
                font-size: 0.9rem !important;
                margin: 0 0 0.05rem 0 !important;
            }

            #last-update-time {
                font-size: 0.7rem !important;
            }

            /* Improve form row appearance */
            .form-row {
                border-radius: 2px;
                transition: background-color 0.2s;
            }

            .form-row:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }

            /* Better spacing in control panel */
            .control-panel-section {
                margin-bottom: 0.1rem !important;
            }

            .control-panel-content {
                padding: 0.1rem !important;
            }

            /* Better appearance for section headers */
            .control-panel h3 {
                background-color: rgba(0, 0, 0, 0.2);
                padding: 0.1rem !important;
                border-radius: 3px;
            }

            /* Optimize file selector dropdown heights */
            .custom-dropdown {
                margin-bottom: 0 !important;
            }

            /* Ensure horizontal time radio display */
            .time-range-radio {
                display: flex !important;
                flex-direction: row !important;
                flex-wrap: wrap !important;
                justify-content: space-around !important;
            }

            /* Make headers stand out better */
            .control-panel h2, .control-panel h3, .control-panel h4 {
                font-weight: 500 !important;
            }

            /* Adjust spacing between control panel and file selectors */
            .control-panel > div:not(:last-child) {
                margin-bottom: 0.1rem !important;
            }

            /* Remove excess margin in ventilation panel */
            .ventilation-panel {
                margin-top: 0 !important;
                padding-top: 0 !important;
            }

            /* Ensure slider has minimal but sufficient height */
            .rc-slider {
                height: 14px !important;
                margin: 0.1rem 0 !important;
            }

            /* Make slider handle easier to grab but visually compact */
            .rc-slider-handle {
                width: 12px !important;
                height: 12px !important;
                margin-top: -4px !important;
                border-width: 1px !important;
            }

            /* Ensure column spacing is minimal */
            .column-left, .column-middle, .column-right {
                margin: 0 !important;
            }

            @media (min-width: 992px) {
                .column-middle {
                    margin-left: 0.1rem !important;
                }
                
                .column-right {
                    margin-left: 0.1rem !important;
                }
            }

            /* Fix any possible overflow issues */
            .dash-container, .main-grid, .column-left, .column-middle, .column-right {
                overflow: hidden !important;
            }

            .scrollable-content {
                overflow-y: auto !important;
            }

            /* Ensure the entire app uses all available viewport space */
            body, html {
                height: 100% !important;
                width: 100% !important;
                overflow: hidden !important;
            }

            .dash-container {
                height: 100vh !important;
                width: 100vw !important;
                overflow: hidden !important;
            }

            .main-grid {
                height: calc(100vh - 10px) !important;
            }

            /* Optimize header section */
            .column-left > div:first-child {
                margin-bottom: 0.05rem !important;
                padding: 0 !important;
            }

            /* Add subtle visual separation between sections */
            .control-panel-section {
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                padding-bottom: 0.1rem;
            }

            .control-panel-section:last-child {
                border-bottom: none;
            }

            /* Ultra compact ventilation slider */
            .ventilation-slider .rc-slider-mark-text {
                font-size: 0.55rem !important;
            }

            /* Fix dropdown menu spacing */
            .Select-menu-outer {
                margin-top: -1px !important;
            }

            .Select-option {
                padding: 2px 4px !important;
                font-size: 0.65rem !important;
            }

            /* Streamline file selector grid */
            .file-selector-grid {
                display: grid !important;
                grid-template-columns: repeat(2, 1fr) !important;
                gap: 0.1rem !important;
            }

            @media (min-width: 768px) {
                .file-selector-grid {
                    grid-template-columns: repeat(4, 1fr) !important;
                }
                
                .time-selector {
                    grid-column: span 1 !important;
                }
            }

            /* Reduce size of dash components */
            .dash-dropdown, .dash-graph, .dash-slider {
                margin: 0 !important;
            }

            /* Make inputs consistent size */
            .control-panel input[type="text"],
            .control-panel input[type="number"] {
                width: 40px !important;
                box-sizing: border-box !important;
            }                                
            
            .cannabis-icon:hover {
                opacity: 1;
                transform: scale(1.1);
            }
# Add this to the end of your app.index_string (after the last CSS rule)
            .cannabis-icon:hover {
                opacity: 1;
                transform: scale(1.1);
            }
        </style>
    </head>
    <body>
        <svg class="cannabis-icon" viewBox="0 0 200 200">
          <defs>
            <linearGradient id="leafGradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" style="stop-color:#2E7D32;stop-opacity:1" />
              <stop offset="50%" style="stop-color:#4CAF50;stop-opacity:1" />
              <stop offset="100%" style="stop-color:#388E3C;stop-opacity:1" />
            </linearGradient>
            
            <linearGradient id="veinGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" style="stop-color:#1B5E20;stop-opacity:0.6" />
              <stop offset="50%" style="stop-color:#2E7D32;stop-opacity:0.8" />
              <stop offset="100%" style="stop-color:#1B5E20;stop-opacity:0.6" />
            </linearGradient>
          </defs>
          
          <g transform="translate(100, 100) scale(0.3)">
            <!-- Center leaflet -->
            <path d="M0,-180 
                     L3,-175 L1,-173 L4,-168 L2,-166 L5,-161 L3,-159 L6,-154 L4,-152
                     L7,-147 L5,-145 L8,-140 L6,-138 L9,-133 L7,-131 L10,-126
                     L8,-124 L11,-119 L9,-117 L12,-112 L10,-110 L13,-105
                     C16,-80 18,-55 14,-30
                     C10,-15 5,-5 0,0
                     C-5,-5 -10,-15 -14,-30
                     C-18,-55 -16,-80 -13,-105
                     L-10,-110 L-12,-112 L-9,-117 L-11,-119 L-8,-124 L-10,-126 L-7,-131
                     L-9,-133 L-6,-138 L-8,-140 L-5,-145 L-7,-147 L-4,-152 L-6,-154
                     L-3,-159 L-5,-161 L-2,-166 L-4,-168 L-1,-173 L-3,-175 Z" 
                  fill="url(#leafGradient)" 
                  stroke="#1B5E20" 
                  stroke-width="0.5"/>
            
            <!-- Upper leaves -->
            <g transform="rotate(-40)">
              <path d="M0,-140 
                       L3,-135 L1,-133 L4,-128 L2,-126 L5,-121 L3,-119 L6,-114
                       L4,-112 L7,-107 L5,-105 L8,-100 L6,-98 L9,-93 L7,-91
                       C10,-70 12,-50 8,-30
                       C5,-15 2,-5 0,0
                       C-2,-5 -5,-15 -8,-30
                       C-12,-50 -10,-70 -7,-91
                       L-9,-93 L-6,-98 L-8,-100 L-5,-105 L-7,-107 L-4,-112
                       L-6,-114 L-3,-119 L-5,-121 L-2,-126 L-4,-128 L-1,-133 L-3,-135 Z"
                    fill="url(#leafGradient)" 
                    stroke="#1B5E20" 
                    stroke-width="0.5"/>
            </g>
            <g transform="rotate(40)">
              <path d="M0,-140 
                       L3,-135 L1,-133 L4,-128 L2,-126 L5,-121 L3,-119 L6,-114
                       L4,-112 L7,-107 L5,-105 L8,-100 L6,-98 L9,-93 L7,-91
                       C10,-70 12,-50 8,-30
                       C5,-15 2,-5 0,0
                       C-2,-5 -5,-15 -8,-30
                       C-12,-50 -10,-70 -7,-91
                       L-9,-93 L-6,-98 L-8,-100 L-5,-105 L-7,-107 L-4,-112
                       L-6,-114 L-3,-119 L-5,-121 L-2,-126 L-4,-128 L-1,-133 L-3,-135 Z"
                    fill="url(#leafGradient)" 
                    stroke="#1B5E20" 
                    stroke-width="0.5"/>
            </g>
            
            <g transform="rotate(-75)">
              <path d="M0,-120 
                       L3,-115 L1,-113 L4,-108 L2,-106 L5,-101 L3,-99 L6,-94
                       L4,-92 L7,-87 L5,-85 L8,-80 L6,-78 L9,-73 L7,-71
                       C10,-55 12,-40 8,-25
                       C5,-12 2,-4 0,0
                       C-2,-4 -5,-12 -8,-25
                       C-12,-40 -10,-55 -7,-71
                       L-9,-73 L-6,-78 L-8,-80 L-5,-85 L-7,-87 L-4,-92
                       L-6,-94 L-3,-99 L-5,-101 L-2,-106 L-4,-108 L-1,-113 L-3,-115 Z"
                    fill="url(#leafGradient)" 
                    stroke="#1B5E20" 
                    stroke-width="0.5"/>
            </g>
            <g transform="rotate(75)">
              <path d="M0,-120 
                       L3,-115 L1,-113 L4,-108 L2,-106 L5,-101 L3,-99 L6,-94
                       L4,-92 L7,-87 L5,-85 L8,-80 L6,-78 L9,-73 L7,-71
                       C10,-55 12,-40 8,-25
                       C5,-12 2,-4 0,0
                       C-2,-4 -5,-12 -8,-25
                       C-12,-40 -10,-55 -7,-71
                       L-9,-73 L-6,-78 L-8,-80 L-5,-85 L-7,-87 L-4,-92
                       L-6,-94 L-3,-99 L-5,-101 L-2,-106 L-4,-108 L-1,-113 L-3,-115 Z"
                    fill="url(#leafGradient)" 
                    stroke="#1B5E20" 
                    stroke-width="0.5"/>
            </g>
            
            <!-- Modified bottom leaves with new angles and smaller size -->
            <g transform="rotate(110) scale(0.6)">
              <path d="M0,-90 
                       L3,-85 L1,-83 L4,-78 L2,-76 L5,-71 L3,-69 L6,-64
                       L4,-62 L7,-57 L5,-55 L8,-50
                       C12,-35 14,-20 10,-10
                       C6,-4 2,-1 0,0
                       C-2,-1 -6,-4 -10,-10
                       C-14,-20 -12,-35 -8,-50
                       L-9,-55 L-6,-57 L-8,-62 L-5,-64 L-7,-69 L-4,-71
                       L-6,-76 L-3,-78 L-5,-83 L-2,-85 Z"
                    fill="url(#leafGradient)" 
                    stroke="#1B5E20" 
                    stroke-width="0.5"/>
            </g>
            <g transform="rotate(250) scale(0.6)">
              <path d="M0,-90 
                       L3,-85 L1,-83 L4,-78 L2,-76 L5,-71 L3,-69 L6,-64
                       L4,-62 L7,-57 L5,-55 L8,-50
                       C12,-35 14,-20 10,-10
                       C6,-4 2,-1 0,0
                       C-2,-1 -6,-4 -10,-10
                       C-14,-20 -12,-35 -8,-50
                       L-9,-55 L-6,-57 L-8,-62 L-5,-64 L-7,-69 L-4,-71
                       L-6,-76 L-3,-78 L-5,-83 L-2,-85 Z"
                    fill="url(#leafGradient)" 
                    stroke="#1B5E20" 
                    stroke-width="0.5"/>
            </g>
            
            <!-- Veining -->
            <g opacity="0.7">
              <path d="M0,0 L0,-180" 
                    stroke="url(#veinGradient)" 
                    stroke-width="0.8"/>
              
              <path d="M0,-170 L-4,-165 M0,-170 L4,-165
                       M0,-150 L-5,-145 M0,-150 L5,-145
                       M0,-130 L-6,-125 M0,-130 L6,-125
                       M0,-110 L-5,-105 M0,-110 L5,-105
                       M0,-90 L-4,-85 M0,-90 L4,-85
                       M0,-70 L-3,-65 M0,-70 L3,-65
                       M0,-50 L-2,-45 M0,-50 L2,-45"
                    stroke="url(#veinGradient)" 
                    stroke-width="0.4"/>
            </g>
            
            <!-- Stem -->
            <path d="M0,0 L0,18 C-1,20 1,20 0,18" 
                  stroke="#2E7D32" 
                  stroke-width="1" 
                  fill="none"/>
          </g>
        </svg>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# Continuing with the callbacks

# Update camera feed callback with responsive design
@app.callback(
    Output('camera-images-container', 'children'),
    [Input('interval-component', 'n_intervals')]
)
def update_camera_feed(n):
    """Update the camera feed images with responsive design."""
    try:
        images = get_latest_images()
        if not images:
            return html.Div("No camera feeds available", 
                          style={'color': 'var(--text-secondary)', 'textAlign': 'center'})
        
        return html.Div([
            html.Div([
                html.Div([
                    html.H4(f"Camera {port + 1}", 
                           style={'color': 'var(--text-primary)', 'marginBottom': '0.5rem'}),
                    html.Div([
                        html.Span("Last Capture: ", style={'color': 'var(--text-secondary)'}),
                        html.Span(img_data['timestamp'], style={'color': 'var(--accent)'})
                    ], style={'marginBottom': '0.5rem'}),
                    html.Img(
                        src=f"data:image/jpeg;base64,{img_data['image']}",
                        style={
                            'transform': 'rotate(180deg)'
                        }
                    )
                ], className='camera-card mobile-padding')
                for port, img_data in sorted(images.items())
            ], className='camera-grid')
        ])
    except Exception as e:
        print(f"Error in update_camera_feed: {e}")
        return html.Div(f"Error loading camera feeds: {str(e)}", 
                       style={'color': 'red', 'textAlign': 'center'})

# Gauge update callback
@app.callback(
    [
        # Spinnenfarm Eintritt (Sensor 1)
        Output('sensor1-temp-gauge', 'figure'),
        Output('sensor1-humidity-gauge', 'figure'),
        Output('sensor1-vpd-gauge', 'figure'),
        
        # Schwarzebox Eintritt (Sensor 2)
        Output('sensor2-temp-gauge', 'figure'),
        Output('sensor2-humidity-gauge', 'figure'),
        Output('sensor2-vpd-gauge', 'figure'),
        
        # Raum (Sensor 3)
        Output('sensor3-temp-gauge', 'figure'),
        Output('sensor3-humidity-gauge', 'figure'),
        Output('sensor3-vpd-gauge', 'figure'),
        
        # Spinnenfarm Austritt (Sensor 4)
        Output('sensor4-temp-gauge', 'figure'),
        Output('sensor4-humidity-gauge', 'figure'),
        
        # Schwarzebox Austritt (Sensor 5)
        Output('sensor5-temp-gauge', 'figure'),
        Output('sensor5-humidity-gauge', 'figure'),
        
        # Soil Sensors
        Output('soil1-moisture-gauge', 'figure'),
        Output('soil1-temp-gauge', 'figure'),
        Output('soil2-moisture-gauge', 'figure'),
        Output('soil2-temp-gauge', 'figure'),
        
        # Value displays
        Output('sensor1-temp-value', 'children'),
        Output('sensor1-humidity-value', 'children'),
        Output('sensor1-vpd-value', 'children'),
        Output('sensor2-temp-value', 'children'),
        Output('sensor2-humidity-value', 'children'),
        Output('sensor2-vpd-value', 'children'),
        Output('sensor3-temp-value', 'children'),
        Output('sensor3-humidity-value', 'children'),
        Output('sensor3-vpd-value', 'children'),
        Output('sensor4-temp-value', 'children'),
        Output('sensor4-humidity-value', 'children'),
        Output('sensor5-temp-value', 'children'),
        Output('sensor5-humidity-value', 'children'),
        Output('soil1-moisture-value', 'children'),
        Output('soil1-temp-value', 'children'),
        Output('soil2-moisture-value', 'children'),
        Output('soil2-temp-value', 'children')
    ],
    [Input('interval-component', 'n_intervals')]
)
def update_gauges(n_intervals):
    try:
        # Get current day's files
        current_file = get_current_day_file(DHT22_DATA_DIR, 'humidity')
        current_soil = get_current_day_file(SOIL_DATA_DIR, 'soil_data')
        
        # Initialize gauge figures and value displays
        gauge_figures = []
        value_displays = []
        
        def create_gauge_figure(value, min_val, max_val, ranges, title=''):
            """Create a gauge figure with the specified parameters."""
            return {
                'data': [{
                    'type': 'indicator',
                    'mode': 'gauge',
                    'value': value,
                    'gauge': {
                        'axis': {'range': [min_val, max_val]},
                        'bar': {'color': "darkgray"},
                        'steps': [
                            {'range': [min_val, ranges[0][0]], 'color': "#FF4444"},
                            {'range': [ranges[0][0], ranges[0][1]], 'color': "#FFA500"},
                            {'range': [ranges[0][1], ranges[1][0]], 'color': "#44FF44"},
                            {'range': [ranges[1][0], ranges[1][1]], 'color': "#FFA500"},
                            {'range': [ranges[1][1], max_val], 'color': "#FF4444"}
                        ],
                        'threshold': {
                            'line': {'color': "white", 'width': 2},
                            'thickness': 0.75,
                            'value': value
                        }
                    }
                }],
                'layout': {
                    'height': 80,
                    'margin': {'l': 7, 'r': 7, 't': 7, 'b': 7},
                    'paper_bgcolor': '#1a1a1a',
                    'font': {'color': "white", 'size': 6},
                    'showlegend': False
                }
            }
        
        if current_file:
            dht_df = load_dht22_data(current_file)
            if not dht_df.empty:
                latest_dht = dht_df.iloc[-1]
                
                # Define ranges
                temp_ranges = [(0, 15), (15, 20), (20, 28), (28, 35), (35, 40)]
                hum_ranges = [(0, 40), (40, 50), (50, 70), (70, 80), (80, 100)]
                vpd_ranges = [(0, 0.8), (0.8, 1.0), (1.0, 1.2), (1.2, 1.5), (1.5, 3.0)]
                
                # Create gauge figures in exact order matching the callback outputs
                for sensor_id in range(1, 6):
                    temp = latest_dht.get(f'TemperatureSensor{sensor_id}', 0)
                    hum = latest_dht.get(f'HumiditySensor{sensor_id}', 0)
                    
                    if sensor_id <= 3:  # Sensors 1-3 have temp, humidity, and VPD
                        vpd = calculate_vpd(temp, hum)
                        # Add temperature gauge
                        gauge_figures.append(create_gauge_figure(temp, 0, 40, [(15, 20), (28, 35)]))
                        # Add humidity gauge
                        gauge_figures.append(create_gauge_figure(hum, 0, 100, [(40, 50), (70, 80)]))
                        # Add VPD gauge
                        gauge_figures.append(create_gauge_figure(vpd, 0, 3, [(0.8, 1.0), (1.2, 1.5)]))
                        # Add value displays
                        value_displays.extend([
                            f"{temp:.1f}°C",
                            f"{hum:.1f}%",
                            f"{vpd:.2f} kPa"
                        ])
                    else:  # Sensors 4-5 have only temp and humidity
                        # Add temperature gauge
                        gauge_figures.append(create_gauge_figure(temp, 0, 40, [(15, 20), (28, 35)]))
                        # Add humidity gauge
                        gauge_figures.append(create_gauge_figure(hum, 0, 100, [(40, 50), (70, 80)]))
                        # Add value displays
                        value_displays.extend([
                            f"{temp:.1f}°C",
                            f"{hum:.1f}%"
                        ])
        
        # Add soil sensor gauges
        if current_soil:
            soil_df = load_soil_data(current_soil)
            if not soil_df.empty:
                latest_soil = soil_df.iloc[-1]
                moisture_ranges = [(0, 300), (300, 400), (400, 600), (600, 700), (700, 1000)]
                
                for sensor_id in range(1, 3):
                    moisture = latest_soil.get(f'Moisture{sensor_id}', 0)
                    temp = latest_soil.get(f'Temperature{sensor_id}', 0)
                    
                    # Add moisture gauge
                    gauge_figures.append(create_gauge_figure(moisture, 0, 1000, [(300, 400), (600, 700)]))
                    # Add temperature gauge
                    gauge_figures.append(create_gauge_figure(temp, 0, 40, [(15, 20), (28, 35)]))
                    # Add value displays
                    value_displays.extend([
                        f"{moisture:.0f}",
                        f"{temp:.1f}°C"
                    ])
        
        # Fill in any missing gauges with empty/zero values
        while len(gauge_figures) < 17:  # Total number of expected gauges
            gauge_figures.append(create_gauge_figure(0, 0, 100, [(20, 40), (60, 80)]))
            
        # Fill in any missing value displays
        while len(value_displays) < 17:  # Total number of expected value displays
            value_displays.append("N/A")
        
        return gauge_figures + value_displays
        
    except Exception as e:
        print(f"Error updating gauges: {str(e)}")
        # Return empty figures and N/A values
        empty_figures = [create_gauge_figure(0, 0, 100, [(20, 40), (60, 80)])] * 17
        empty_values = ["N/A"] * 17
        return empty_figures + empty_values

# Dashboard update callback
@app.callback(
    [Output('temperature-graph', 'figure'),
     Output('humidity-graph', 'figure'),
     Output('vpd-graph', 'figure'),
     Output('soil-temperature-graph', 'figure'),
     Output('soil-moisture-graph', 'figure'),
     Output('ventilation-power-graph', 'figure'),
     Output('stats-container', 'children')],
    [Input('file-selector', 'value'),
     Input('soil-file-selector', 'value'),
     Input('power-file-selector', 'value'),
     Input('time-range', 'value'),
     Input('interval-component', 'n_intervals')]
)
def update_dashboard(selected_file, selected_soil_file, selected_power_file, 
                    time_range, n_intervals):
    try:
        # Load data
        dht_df = load_dht22_data(selected_file) if selected_file else pd.DataFrame()
        soil_df = load_soil_data(selected_soil_file) if selected_soil_file else pd.DataFrame()
        power_df = load_ventilation_power_data(selected_power_file) if selected_power_file else pd.DataFrame()

        # Debug information about loaded power data
        if not power_df.empty:
            print(f"Power DataFrame before time filter: {len(power_df)} rows")
            print(f"Power DF columns: {power_df.columns.tolist()}")
            print(f"First row: {power_df.iloc[0].to_dict()}")
            if 'Timestamp' in power_df.columns:
                print(f"Timestamp type: {type(power_df['Timestamp'].iloc[0])}")
                print(f"Time range: {power_df['Timestamp'].min()} to {power_df['Timestamp'].max()}")

        # Explicit timestamp handling for power data
        if not power_df.empty and 'Timestamp' in power_df.columns:
            # Force conversion to datetime regardless of original type
            power_df['Timestamp'] = pd.to_datetime(power_df['Timestamp'], errors='coerce')
            # Drop rows with failed timestamp conversion
            power_df = power_df.dropna(subset=['Timestamp'])
            print(f"Power DataFrame after timestamp conversion: {len(power_df)} rows")

        # Apply time range filter to all dataframes
        dht_df = apply_time_range_filter(dht_df, time_range)
        soil_df = apply_time_range_filter(soil_df, time_range)
        
        # Manual time filtering for power data
        if time_range != 'all' and not power_df.empty and 'Timestamp' in power_df.columns:
            hours = int(time_range[:-1])
            cutoff = datetime.now() - timedelta(hours=hours)
            print(f"Applying manual time filter to power data: {cutoff}")
            power_df_filtered = power_df[power_df['Timestamp'] >= cutoff]
            print(f"Power data filtered: {len(power_df)} -> {len(power_df_filtered)} rows")
            power_df = power_df_filtered
        
        # Debug info after filtering
        if not power_df.empty:
            print(f"Power DataFrame after time filter: {len(power_df)} rows")
            if 'Timestamp' in power_df.columns and not power_df.empty:
                print(f"Filtered time range: {power_df['Timestamp'].min()} to {power_df['Timestamp'].max()}")

        # Create figures with filtered data
        temp_fig = create_temperature_figure(dht_df)
        hum_fig = create_humidity_figure(dht_df)
        vpd_fig = create_vpd_figure(dht_df)
        soil_temp_fig = create_soil_temperature_figure(soil_df)
        soil_moisture_fig = create_soil_moisture_figure(soil_df)
        
        # Create power figure with filtered data
        power_fig = create_ventilation_power_figure(power_df)

        # Calculate statistics from filtered data
        stats = calculate_stats(dht_df, soil_df)
        stats_cards = _create_detailed_stats_cards(stats)

        return (
            temp_fig, hum_fig, vpd_fig, 
            soil_temp_fig, soil_moisture_fig, power_fig,
            html.Div(stats_cards, style={
                'display': 'flex',
                'flexWrap': 'wrap',
                'justifyContent': 'center',
                'alignItems': 'flex-start',
                'gap': '0.5rem'
            })
        )

    except Exception as e:
        print(f"Error in update_dashboard: {str(e)}")
        print(traceback.format_exc())
        return [go.Figure()] * 6 + [html.Div(f"Error: {str(e)}", style={'color': 'red'})]

# Light scheduling callbacks
@app.callback(
    [Output('light-schedule-status', 'children'),
     Output('light2-schedule-status', 'children')],
    [Input('light-schedule-switch', 'on'),
     Input('light2-schedule-switch', 'on')],
    [State('light-on-time', 'value'),
     State('light-off-time', 'value'),
     State('light2-on-time', 'value'),
     State('light2-off-time', 'value')]
)
def update_light_schedules(light1_enabled, light2_enabled, 
                            light1_on_time, light1_off_time, 
                            light2_on_time, light2_off_time):
    # Track statuses for both light systems
    status1 = html.Div("", style={'color': 'var(--text-secondary)'})
    status2 = html.Div("", style={'color': 'var(--text-secondary)'})
    
    # Validate times for both systems
    if not all([light1_on_time, light1_off_time, light2_on_time, light2_off_time]):
        return (
            html.Div("Bitte beide Zeiten einstellen", style={'color': 'red'}),
            html.Div("Bitte beide Zeiten einstellen", style={'color': 'red'})
        )
    
    try:
        # Update first light system
        print(f"Sending light1 schedule: Enabled={light1_enabled}, On={light1_on_time}, Off={light1_off_time}")
        response1 = requests.post('http://localhost:5000/api/light/schedule', 
            json={
                'enabled': light1_enabled,
                'on_time': light1_on_time,
                'off_time': light1_off_time
            }
        )
        
        # Update second light system
        print(f"Sending light2 schedule: Enabled={light2_enabled}, On={light2_on_time}, Off={light2_off_time}")
        response2 = requests.post('http://localhost:5000/api/light2/schedule', 
            json={
                'enabled': light2_enabled,
                'on_time': light2_on_time,
                'off_time': light2_off_time
            }
        )
        
        # Check responses for first light system
        print(f"Light1 response status: {response1.status_code}")
        print(f"Light1 response content: {response1.text}")
        if response1.ok:
            status1 = html.Div("Zeitplan erfolgreich aktualisiert", 
                             style={'color': 'var(--accent)'})
        else:
            status1 = html.Div(f"Fehler: {response1.text}", 
                             style={'color': 'red'})
        
        # Check responses for second light system
        print(f"Light2 response status: {response2.status_code}")
        print(f"Light2 response content: {response2.text}")
        if response2.ok:
            status2 = html.Div("Zeitplan erfolgreich aktualisiert", 
                             style={'color': 'var(--accent)'})
        else:
            status2 = html.Div(f"Fehler: {response2.text}", 
                             style={'color': 'red'})
        
        return status1, status2
    
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}")
        error_status = html.Div(f"Netzwerkfehler: {str(e)}", 
                               style={'color': 'red'})
        return error_status, error_status
    except Exception as e:
        print(f"Unexpected error: {e}")
        error_status = html.Div(f"Unerwarteter Fehler: {str(e)}", 
                               style={'color': 'red'})
        return error_status, error_status

# Initialize light schedules
@app.callback(
    [Output('light-schedule-switch', 'on'),
     Output('light-on-time', 'value'),
     Output('light-off-time', 'value'),
     Output('light2-schedule-switch', 'on'),
     Output('light2-on-time', 'value'),
     Output('light2-off-time', 'value')],
    [Input('interval-component', 'n_intervals')]
)
def init_light_schedules(n):
    try:
        # Fetch for first light system
        response1 = requests.get('http://localhost:5000/api/light/schedule')
        # Fetch for second light system
        response2 = requests.get('http://localhost:5000/api/light2/schedule')
        
        if response1.ok and response2.ok:
            data1 = response1.json()
            data2 = response2.json()
            
            return (
                data1.get('enabled', False),
                data1.get('on_time', '06:00'),
                data1.get('off_time', '00:00'),
                data2.get('enabled', False),
                data2.get('on_time', '06:00'),
                data2.get('off_time', '00:00')
            )
    except Exception as e:
        print(f"Error fetching light schedules: {e}")
    
    return [False, '06:00', '00:00'] * 2

# Valve 1 scheduling callback
@app.callback(
    Output('valve-1-schedule-status', 'children'),
    [Input('valve-1-schedule-switch', 'on'),
     Input('valve-1-schedule-time', 'value'),
     Input('valve-1-duration', 'value')]
)
def update_valve1_schedule(enabled, time, duration):
    try:
        response = requests.post('http://localhost:5000/api/valve1/schedule', 
            json={
                'enabled': enabled,
                'time': time,
                'duration': duration
            }
        )
        
        if response.ok:
            status = "Zeitplan aktiviert" if enabled else "Kein Zeitplan"
            return html.Div(f"{status} um {time}, Dauer: {duration} Minuten", 
                           style={'color': 'var(--accent)', 'fontSize': '0.8rem'})
        else:
            return html.Div("Fehler beim Zeitplan", 
                           style={'color': 'red', 'fontSize': '0.8rem'})
    except Exception as e:
        return html.Div(f"Fehler: {str(e)}", 
                       style={'color': 'red', 'fontSize': '0.8rem'})

# Valve 2 scheduling callback
@app.callback(
    Output('valve-2-schedule-status', 'children'),
    [Input('valve-2-schedule-switch', 'on'),
     Input('valve-2-schedule-time', 'value'),
     Input('valve-2-duration', 'value')]
)
def update_valve2_schedule(enabled, time, duration):
    try:
        response = requests.post('http://localhost:5000/api/valve2/schedule', 
            json={
                'enabled': enabled,
                'time': time,
                'duration': duration
            }
        )
        
        if response.ok:
            status = "Zeitplan aktiviert" if enabled else "Kein Zeitplan"
            return html.Div(f"{status} um {time}, Dauer: {duration} Minuten", 
                           style={'color': 'var(--accent)', 'fontSize': '0.8rem'})
        else:
            return html.Div("Fehler beim Zeitplan", 
                           style={'color': 'red', 'fontSize': '0.8rem'})
    except Exception as e:
        return html.Div(f"Fehler: {str(e)}", 
                       style={'color': 'red', 'fontSize': '0.8rem'})

# Initialize valve 1 schedule
@app.callback(
    [Output('valve-1-schedule-switch', 'on'),
     Output('valve-1-schedule-time', 'value'),
     Output('valve-1-duration', 'value')],
    [Input('interval-component', 'n_intervals')]
)
def init_valve1_schedule(n):
    try:
        response = requests.get('http://localhost:5000/api/valve1/schedule')
        if response.ok:
            data = response.json()
            return (
                data.get('enabled', False),
                data.get('time', '06:00'),
                data.get('duration', 5)
            )
    except:
        pass
    
    return False, '06:00', 5

# Initialize valve 2 schedule
@app.callback(
    [Output('valve-2-schedule-switch', 'on'),
     Output('valve-2-schedule-time', 'value'),
     Output('valve-2-duration', 'value')],
    [Input('interval-component', 'n_intervals')]
)
def init_valve2_schedule(n):
    try:
        response = requests.get('http://localhost:5000/api/valve2/schedule')
        if response.ok:
            data = response.json()
            return (
                data.get('enabled', False),
                data.get('time', '06:00'),
                data.get('duration', 5)
            )
    except:
        pass
    
    return False, '06:00', 5

# Valve 1 control
@app.callback(
    [Output('valve-1-timer', 'children'),
     Output('valve-1-power', 'on'),
     Output('valve-1-state', 'data')],
    [Input('valve-1-power', 'on'),
     Input('valve-1-duration', 'value'),
     Input('timer-interval', 'n_intervals')],
    [State('valve-1-state', 'data')]
)
def handle_valve_1(power_on, duration, n_intervals, valve_state):
    ctx = callback_context
    if not ctx.triggered:
        return ["", False, False]
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    try:
        if trigger_id == 'valve-1-power':
            if power_on:
                # Turn on valve
                response = requests.post('http://localhost:5000/api/relay/1', 
                    json={'status': True, 'duration': duration}
                )
                if response.ok:
                    # Start the timer immediately
                    return [f"Running: {duration:.1f} minutes", True, True]
                else:
                    return ["Error activating valve", False, False]
            else:
                # Turn off valve
                response = requests.post('http://localhost:5000/api/relay/1', 
                    json={'status': False}
                )
                return ["", False, False]
                
        elif trigger_id == 'timer-interval':
            # Always check status on timer tick if valve was last known to be on
            try:
                response = requests.get('http://localhost:5000/api/relay/1/status')
                if response.ok:
                    status = response.json()
                    remaining = status.get('remaining_time', 0)
                    active = status.get('active', False)
                    
                    if not active or remaining <= 0:
                        return ["", False, False]
                    
                    return [f"Running: {remaining:.1f} minutes", True, True]
                else:
                    if valve_state:  # Only reset if we thought it was on
                        return ["", False, False]
            except Exception as e:
                print(f"Error checking valve 1 status: {str(e)}")
                if valve_state:  # Only reset if we thought it was on
                    return ["", False, False]
                
    except Exception as e:
        print(f"Error in valve 1 callback: {str(e)}")
        return ["Error", False, False]
        
    # Return current state if nothing changed
    if valve_state:
        try:
            response = requests.get('http://localhost:5000/api/relay/1/status')
            if response.ok:
                status = response.json()
                remaining = status.get('remaining_time', 0)
                active = status.get('active', False)
                if active and remaining > 0:
                    return [f"Running: {remaining:.1f} minutes", True, True]
        except:
            pass
    
    return ["", valve_state, valve_state]

# Valve 2 control
@app.callback(
    [Output('valve-2-timer', 'children'),
     Output('valve-2-power', 'on'),
     Output('valve-2-state', 'data')],
    [Input('valve-2-power', 'on'),
     Input('valve-2-duration', 'value'),
     Input('timer-interval', 'n_intervals')],
    [State('valve-2-state', 'data')]
)
def handle_valve_2(power_on, duration, n_intervals, valve_state):
    ctx = callback_context
    if not ctx.triggered:
        return ["", False, False]
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    try:
        if trigger_id == 'valve-2-power':
            if power_on:
                # Turn on valve
                response = requests.post('http://localhost:5000/api/relay/2', 
                    json={'status': True, 'duration': duration}
                )
                if response.ok:
                    # Start the timer immediately
                    return [f"Running: {duration:.1f} minutes", True, True]
                else:
                    return ["Error activating valve", False, False]
            else:
                # Turn off valve
                response = requests.post('http://localhost:5000/api/relay/2', 
                    json={'status': False}
                )
                return ["", False, False]
                
        elif trigger_id == 'timer-interval':
            # Always check status on timer tick if valve was last known to be on
            try:
                response = requests.get('http://localhost:5000/api/relay/2/status')
                if response.ok:
                    status = response.json()
                    remaining = status.get('remaining_time', 0)
                    active = status.get('active', False)
                    
                    if not active or remaining <= 0:
                        return ["", False, False]
                    
                    return [f"Running: {remaining:.1f} minutes", True, True]
                else:
                    if valve_state:  # Only reset if we thought it was on
                        return ["", False, False]
            except Exception as e:
                print(f"Error checking valve 2 status: {str(e)}")
                if valve_state:  # Only reset if we thought it was on
                    return ["", False, False]
                
    except Exception as e:
        print(f"Error in valve 2 callback: {str(e)}")
        return ["Error", False, False]
        
    # Return current state if nothing changed
    if valve_state:
        try:
            response = requests.get('http://localhost:5000/api/relay/2/status')
            if response.ok:
                status = response.json()
                remaining = status.get('remaining_time', 0)
                active = status.get('active', False)
                if active and remaining > 0:
                    return [f"Running: {remaining:.1f} minutes", True, True]
        except:
            pass
    
    return ["", valve_state, valve_state]

# Ventilation mode control
@app.callback(
    [Output('ventilation-speed-slider', 'disabled'),
     Output('ventilation-status', 'children')],
    [Input('ventilation-auto-switch', 'on'),
     Input('ventilation-target-vpd', 'value'),
     Input('interval-component', 'n_intervals')]
)
def update_ventilation_mode(auto_enabled, target_vpd, n_intervals):
    if auto_enabled:
        try:
            # Update port to 5001
            response = requests.post('http://localhost:5001/api/ventilation/auto',
                json={'enabled': True, 'target_vpd': target_vpd}
            )
            if response.ok:
                data = response.json()
                return True, f"VPD Automatik aktiv (Ziel: {target_vpd} kPa), Speed: {data.get('current_speed', 0)}%"
            else:
                error_msg = response.json().get('error', 'Unknown error')
                print(f"Ventilation API error: {error_msg}")
                return True, f"Fehler: {error_msg}"
        except Exception as e:
            print(f"Ventilation control error: {str(e)}")
            print(traceback.format_exc())
            return True, f"Verbindungsfehler: {str(e)}"
    else:
        try:
            # Update port to 5001
            response = requests.post('http://localhost:5001/api/ventilation/auto',
                json={'enabled': False}
            )
            if response.ok:
                return False, "Manueller Modus"
            else:
                error_msg = response.json().get('error', 'Unknown error')
                return False, f"Fehler: {error_msg}"
        except Exception as e:
            print(f"Ventilation control error: {str(e)}")
            return False, f"Verbindungsfehler: {str(e)}"

# Ventilation speed control
@app.callback(
    Output('ventilation-speed-slider', 'value'),
    [Input('ventilation-speed-slider', 'value'),
     Input('interval-component', 'n_intervals')]
)
def update_ventilation_speed(speed, n_intervals):
    ctx = callback_context
    if not ctx.triggered:
        return 0
        
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if trigger_id == 'ventilation-speed-slider':
        try:
            # Update port to 5001
            response = requests.post('http://localhost:5001/api/ventilation/speed',
                json={'speed': speed}
            )
            if response.ok:
                return response.json()['speed']
            else:
                print(f"Error setting speed: {response.json().get('error')}")
                return 0
        except Exception as e:
            print(f"Error setting fan speed: {str(e)}")
            print(traceback.format_exc())
            return 0
    else:
        try:
            # Update port to 5001
            response = requests.get('http://localhost:5001/api/ventilation/speed')
            if response.ok:
                return response.json()['speed']
            else:
                print(f"Error getting speed: {response.json().get('error')}")
        except Exception as e:
            print(f"Error getting fan speed: {str(e)}")
            
    return 0

# File selector update callback
@app.callback(
    [Output('file-selector', 'options'),
     Output('soil-file-selector', 'options'),
     Output('power-file-selector', 'options'),
     Output('file-selector', 'value'),
     Output('soil-file-selector', 'value'),
     Output('power-file-selector', 'value'),
     Output('last-update-time', 'children')],
    [Input('interval-component', 'n_intervals'),
     Input('timer-interval', 'n_intervals')],
    [State('file-selector', 'value'),
     State('soil-file-selector', 'value'),
     State('power-file-selector', 'value'),
     State('last-update-time', 'children')]
)
def update_file_selectors(interval_n, timer_n, current_dht, current_soil, current_power, last_time):
    """Update file selectors and detect midnight transitions"""
    
    ctx = callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None
    
    current_time = datetime.now().strftime("%H:%M:%S")
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    # Timer interval trigger - check for midnight transitions
    if trigger_id == 'timer-interval':
        # Only check once per minute to reduce load
        if timer_n % 60 != 0:
            return [dash.no_update] * 6 + [current_time]
            
        # Extract date from current files
        def extract_date_from_file(file_path):
            if not file_path:
                return None
            match = re.search(r'_(\d{4}-\d{2}-\d{2})', file_path)
            return match.group(1) if match else None
            
        dht_date = extract_date_from_file(current_dht)
        soil_date = extract_date_from_file(current_soil)
        power_date = extract_date_from_file(current_power)
        
        # Check if date has changed
        need_update = (dht_date != current_date) or (soil_date != current_date) or (power_date != current_date)
        
        # Also check if it's near midnight (between 23:59 and 00:01)
        hour, minute = datetime.now().hour, datetime.now().minute
        near_midnight = (hour == 23 and minute >= 59) or (hour == 0 and minute <= 1)
        
        if not (need_update or near_midnight):
            return [dash.no_update] * 6 + [current_time]
        
        print("Date changed or near midnight - forcing file list update")
    
    # Standard interval update or midnight transition
    def format_date_label(filepath):
        match = re.search(r'_(\d{4}-\d{2}-\d{2})', filepath)
        if match:
            date_str = match.group(1)
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                return date_obj.strftime('%d.%m.%Y')
            except ValueError:
                return date_str
        return filepath
    
    # Get fresh file lists
    dht_files = load_csv_files(DHT22_DATA_DIR, 'humidity')
    soil_files = load_csv_files(SOIL_DATA_DIR, 'soil_data')
    power_files = load_csv_files('/home/johagy/ventilation_logs', 'potentiometer_power')
    
    # Get current day files
    current_day_dht = get_current_day_file(DHT22_DATA_DIR, 'humidity')
    current_day_soil = get_current_day_file(SOIL_DATA_DIR, 'soil_data')
    current_day_power = get_current_day_file('/home/johagy/ventilation_logs', 'potentiometer_power')
    
    if trigger_id == 'timer-interval' and not any([current_day_dht, current_day_soil, current_day_power]):
        print("No current day files found, creating empty files if needed")
        # Try creating empty files with headers if they don't exist
        current_day_dht = _ensure_current_day_file(DHT22_DATA_DIR, 'humidity')
        current_day_soil = _ensure_current_day_file(SOIL_DATA_DIR, 'soil_data')
        current_day_power = _ensure_current_day_file('/home/johagy/ventilation_logs', 'potentiometer_power')
    
    # Create options for each selector
    dht_options = [{'label': format_date_label(f), 'value': f} for f in dht_files]
    soil_options = [{'label': format_date_label(f), 'value': f} for f in soil_files]
    power_options = [{'label': format_date_label(f), 'value': f} for f in power_files]
    
    # Update values only if current day file exists and is different
    new_dht_value = current_day_dht if current_day_dht and current_day_dht != current_dht else current_dht
    new_soil_value = current_day_soil if current_day_soil and current_day_soil != current_soil else current_soil
    new_power_value = current_day_power if current_day_power and current_day_power != current_power else current_power
    
    # Ensure we have valid values if the files are available
    if not new_dht_value and dht_files:
        new_dht_value = dht_files[-1]
    if not new_soil_value and soil_files:
        new_soil_value = soil_files[-1]
    if not new_power_value and power_files:
        new_power_value = power_files[-1]
    
    return dht_options, soil_options, power_options, new_dht_value, new_soil_value, new_power_value, current_time

# Run the server
if __name__ == '__main__':
    app.run_server(debug=True, host='0.0.0.0', port=8050)
