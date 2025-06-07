#python3 ~/relay/relay_controller.py

from flask import Flask, request, jsonify
import gpiod
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import sys

# GPIO setup for Pi 5
CHIP_NAME = '/dev/gpiochip4'  # This is the main GPIO chip on Pi 5
RELAY_PINS = {
    1: 13,  # Valve 1
    2: 22,  # Valve 2
    3: 19,  # Grow light
    4: 6    # Grow light 2
}

# Store schedules
light_schedule = {
    'enabled': False,
    'on_time': '06:00',
    'off_time': '00:00'
}

light2_schedule = {
    'enabled': False,
    'on_time': '06:00',
    'off_time': '00:00'
}

valve1_schedule = {
    'enabled': False,
    'time': '06:00',
    'duration': 5
}

valve2_schedule = {
    'enabled': False,
    'time': '06:00',
    'duration': 5
}

valve_states = {
    1: {'active': False, 'end_time': None, 'original_duration': None},
    2: {'active': False, 'end_time': None, 'original_duration': None}
}

class GPIOController:
    def __init__(self):
        self.chip = None
        self.lines = {}
        
    def init_gpio(self):
        """Initialize GPIO with gpiod"""
        try:
            print(f"Initializing GPIO on {CHIP_NAME}")
            self.chip = gpiod.Chip(CHIP_NAME)
            
            # Initialize all relay pins
            for relay_num, pin in RELAY_PINS.items():
                try:
                    line = self.chip.get_line(pin)
                    line.request(consumer="relay_controller", type=gpiod.LINE_REQ_DIR_OUT)
                    line.set_value(1)  # Start with relays OFF (active LOW)
                    self.lines[relay_num] = line
                    print(f"Initialized relay {relay_num} on pin {pin}")
                except Exception as e:
                    print(f"Error setting up pin {pin}: {str(e)}")
                    return False
            
            print("GPIO initialized successfully")
            return True
            
        except Exception as e:
            print(f"Error initializing GPIO: {str(e)}")
            return False
    
    def cleanup(self):
        """Cleanup GPIO resources"""
        for line in self.lines.values():
            try:
                line.release()
            except:
                pass
        if self.chip:
            self.chip.close()
    
    def turn_on_relay(self, relay_num):
        """Turn on relay (set LOW)"""
        try:
            if relay_num in self.lines:
                print(f"Turning ON relay {relay_num}")
                self.lines[relay_num].set_value(0)  # Active LOW
                return True
            return False
        except Exception as e:
            print(f"Error turning on relay {relay_num}: {str(e)}")
            return False
    
    def turn_off_relay(self, relay_num):
        """Turn off relay (set HIGH)"""
        try:
            if relay_num in self.lines:
                print(f"Turning OFF relay {relay_num}")
                self.lines[relay_num].set_value(1)  # Inactive HIGH
                return True
            return False
        except Exception as e:
            print(f"Error turning off relay {relay_num}: {str(e)}")
            return False
    
    def get_relay_state(self, relay_num):
        """Get current state of relay"""
        try:
            if relay_num in self.lines:
                value = self.lines[relay_num].get_value()
                return not value  # Invert because active LOW
            return False
        except Exception as e:
            print(f"Error getting relay {relay_num} state: {str(e)}")
            return False

# Create Flask app and GPIO controller
app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()
gpio = GPIOController()

def _cleanup_valve(valve_num):
    """Clean up valve state with explicit relay control"""
    if valve_num not in [1, 2]:
        return
        
    print(f"Cleaning up valve {valve_num}")
    success = gpio.turn_off_relay(valve_num)
    
    if success:
        valve_states[valve_num]['active'] = False
        valve_states[valve_num]['end_time'] = None
        valve_states[valve_num]['original_duration'] = None
    
    # Clean up any existing jobs for this valve
    for job_id in [f'valve{valve_num}_manual_off', f'valve{valve_num}_schedule_off']:
        try:
            scheduler.remove_job(job_id)
        except:
            pass

def schedule_valve(valve_num):
    """Schedule a valve based on its schedule settings"""
    schedule_dict = valve1_schedule if valve_num == 1 else valve2_schedule
    
    # Remove any existing valve schedules for this valve
    for job in scheduler.get_jobs():
        if job.id.startswith(f'valve{valve_num}_'):
            scheduler.remove_job(job.id)
    
    if not schedule_dict['enabled']:
        gpio.turn_off_relay(valve_num)  # Turn off valve when schedule is disabled
        return
    
    # Schedule valve ON
    hour, minute = map(int, schedule_dict['time'].split(':'))
    scheduler.add_job(
        func=lambda: automatic_single_valve(valve_num, schedule_dict['duration']),
        trigger='cron',
        hour=hour,
        minute=minute,
        id=f'valve{valve_num}_schedule'
    )

def automatic_single_valve(valve_num, duration_minutes):
    """Run irrigation for a single valve with state tracking"""
    try:
        print(f"Starting automatic valve {valve_num} for {duration_minutes} minutes")
        
        # Clean up any existing state first
        _cleanup_valve(valve_num)
        
        # Turn on valve and set state
        gpio.turn_on_relay(valve_num)
        end_time = datetime.now() + timedelta(minutes=duration_minutes)
        valve_states[valve_num]['active'] = True
        valve_states[valve_num]['end_time'] = end_time
        valve_states[valve_num]['original_duration'] = duration_minutes
        
        # Schedule turn off with cleanup
        scheduler.add_job(
            func=_cleanup_valve,
            trigger='date',
            run_date=end_time,
            args=[valve_num],
            id=f'valve{valve_num}_schedule_off',
            replace_existing=True,
            misfire_grace_time=None
        )
    except Exception as e:
        print(f"Error in automatic_single_valve for valve {valve_num}: {str(e)}")
        _cleanup_valve(valve_num)  # Ensure valve is off on error

def schedule_light():
    """Schedule the grow light based on on_time and off_time"""
    # Remove any existing light schedules
    for job in scheduler.get_jobs():
        if job.id.startswith('light1_'):
            scheduler.remove_job(job.id)
    
    if not light_schedule['enabled']:
        gpio.turn_off_relay(3)  # Turn off grow light when schedule is disabled
        return
    
    # Schedule light ON
    on_hour, on_minute = map(int, light_schedule['on_time'].split(':'))
    scheduler.add_job(
        func=gpio.turn_on_relay,
        trigger='cron',
        hour=on_hour,
        minute=on_minute,
        args=[3],
        id='light1_on'
    )
    
    # Schedule light OFF
    off_hour, off_minute = map(int, light_schedule['off_time'].split(':'))
    scheduler.add_job(
        func=gpio.turn_off_relay,
        trigger='cron',
        hour=off_hour,
        minute=off_minute,
        args=[3],
        id='light1_off'
    )
    
    # Set initial state based on current time
    current_time = datetime.now().strftime('%H:%M')
    if light_schedule['on_time'] <= current_time < light_schedule['off_time']:
        gpio.turn_on_relay(3)
    else:
        gpio.turn_off_relay(3)

def schedule_light2():
    """Schedule the second grow light based on on_time and off_time"""
    # Remove any existing light2 schedules
    for job in scheduler.get_jobs():
        if job.id.startswith('light2_'):
            scheduler.remove_job(job.id)
    
    if not light2_schedule['enabled']:
        gpio.turn_off_relay(4)  # Turn off light2 when schedule is disabled
        return
    
    # Schedule light2 ON
    on_hour, on_minute = map(int, light2_schedule['on_time'].split(':'))
    scheduler.add_job(
        func=gpio.turn_on_relay,
        trigger='cron',
        hour=on_hour,
        minute=on_minute,
        args=[4],
        id='light2_on'
    )
    
    # Schedule light2 OFF
    off_hour, off_minute = map(int, light2_schedule['off_time'].split(':'))
    scheduler.add_job(
        func=gpio.turn_off_relay,
        trigger='cron',
        hour=off_hour,
        minute=off_minute,
        args=[4],
        id='light2_off'
    )
    
    # Set initial state based on current time
    current_time = datetime.now().strftime('%H:%M')
    if light2_schedule['on_time'] <= current_time < light2_schedule['off_time']:
        gpio.turn_on_relay(4)
    else:
        gpio.turn_off_relay(4)

@app.route('/api/relay/<int:relay_num>/status', methods=['GET'])
def get_relay_status(relay_num):
    """Get current status of a relay/valve"""
    if relay_num not in RELAY_PINS:
        return jsonify({'error': 'Invalid relay number'}), 400
    
    try:
        # Get current GPIO state
        current_state = gpio.get_relay_state(relay_num)
        
        response = {
            'active': current_state,
            'remaining_time': 0,
            'original_duration': None
        }
        
        # Add valve-specific information
        if relay_num in [1, 2]:
            state = valve_states[relay_num]
            if state['active'] and state['end_time']:
                now = datetime.now()
                if now >= state['end_time']:
                    # Valve time has expired
                    _cleanup_valve(relay_num)
                    response['active'] = False
                    response['remaining_time'] = 0
                    response['original_duration'] = None
                else:
                    remaining = (state['end_time'] - now).total_seconds() / 60
                    response['remaining_time'] = remaining
                    response['original_duration'] = state.get('original_duration')
                    response['active'] = True
                    
        return jsonify(response)
    except Exception as e:
        print(f"Error getting relay {relay_num} status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/relay/<int:relay_num>/on', methods=['POST'])
def turn_relay_on(relay_num):
    """Direct endpoint to turn on a relay"""
    if relay_num not in RELAY_PINS:
        return jsonify({'error': 'Invalid relay number'}), 400
    
    try:
        success = gpio.turn_on_relay(relay_num)
        if not success:
            return jsonify({'error': 'Failed to turn on relay'}), 500
            
        return jsonify({
            'success': True,
            'relay': relay_num,
            'status': 'on'
        })
    except Exception as e:
        print(f"Error turning on relay {relay_num}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/relay/<int:relay_num>/off', methods=['POST'])
def turn_relay_off(relay_num):
    """Direct endpoint to turn off a relay"""
    if relay_num not in RELAY_PINS:
        return jsonify({'error': 'Invalid relay number'}), 400
    
    try:
        if relay_num in [1, 2]:
            _cleanup_valve(relay_num)
        else:
            success = gpio.turn_off_relay(relay_num)
            if not success:
                return jsonify({'error': 'Failed to turn off relay'}), 500
                
        return jsonify({
            'success': True,
            'relay': relay_num,
            'status': 'off'
        })
    except Exception as e:
        print(f"Error turning off relay {relay_num}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/relay/<int:relay_num>', methods=['POST'])
def control_relay(relay_num):
    """Unified relay control endpoint with explicit state management"""
    if relay_num not in RELAY_PINS:
        return jsonify({'error': 'Invalid relay number'}), 400
    
    data = request.get_json()
    status = data.get('status', False)
    duration = int(data.get('duration', 0))
    
    try:
        if status:
            # Turn on relay
            success = gpio.turn_on_relay(relay_num)
            if not success:
                return jsonify({'error': 'Failed to turn on relay'}), 500
            
            # Handle valve-specific logic
            if relay_num in [1, 2]:
                valve_states[relay_num]['active'] = True
                if duration > 0:
                    end_time = datetime.now() + timedelta(minutes=duration)
                    valve_states[relay_num]['end_time'] = end_time
                    valve_states[relay_num]['original_duration'] = duration
                    
                    # Schedule turn off
                    scheduler.add_job(
                        func=_cleanup_valve,
                        trigger='date',
                        run_date=end_time,
                        args=[relay_num],
                        id=f'valve{relay_num}_manual_off',
                        replace_existing=True,
                        misfire_grace_time=None
                    )
        else:
            # Turn off relay/valve
            if relay_num in [1, 2]:
                _cleanup_valve(relay_num)
            else:
                success = gpio.turn_off_relay(relay_num)
                if not success:
                    return jsonify({'error': 'Failed to turn off relay'}), 500
                
        return jsonify({
            'success': True, 
            'relay': relay_num, 
            'status': status,
            'duration': duration if status else 0
        })
    except Exception as e:
        print(f"Error controlling relay {relay_num}: {str(e)}")
        if relay_num in [1, 2]:
            _cleanup_valve(relay_num)
        return jsonify({'error': str(e)}), 500

@app.route('/api/schedule', methods=['POST'])
def set_schedule():
    data = request.get_json()
    start_time = data.get('start_time')
    duration = data.get('duration')
    
    if not start_time or not duration:
        return jsonify({'error': 'Missing required parameters'}), 400
    
    try:
        schedule_irrigation(start_time, duration)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/light/schedule', methods=['POST'])
def set_light_schedule():
    data = request.get_json()
    
    # Update schedule settings
    light_schedule['enabled'] = data.get('enabled', False)
    if 'on_time' in data:
        light_schedule['on_time'] = data['on_time']
    if 'off_time' in data:
        light_schedule['off_time'] = data['off_time']
    
    try:
        schedule_light()
        return jsonify({
            'success': True,
            'schedule': light_schedule
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/light/schedule', methods=['GET'])
def get_light_schedule():
    return jsonify(light_schedule)

@app.route('/api/light2/schedule', methods=['POST'])
def set_light2_schedule():
    data = request.get_json()
    
    # Update schedule settings
    light2_schedule['enabled'] = data.get('enabled', False)
    if 'on_time' in data:
        light2_schedule['on_time'] = data['on_time']
    if 'off_time' in data:
        light2_schedule['off_time'] = data['off_time']
    
    try:
        schedule_light2()
        return jsonify({
            'success': True,
            'schedule': light2_schedule
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/light2/schedule', methods=['GET'])
def get_light2_schedule():
    return jsonify(light2_schedule)

@app.route('/api/valve1/schedule', methods=['POST'])
def set_valve1_schedule():
    data = request.get_json()
    
    # Update schedule settings
    valve1_schedule['enabled'] = data.get('enabled', False)
    if 'time' in data:
        valve1_schedule['time'] = data['time']
    if 'duration' in data:
        valve1_schedule['duration'] = data['duration']
    
    try:
        schedule_valve(1)
        return jsonify({
            'success': True,
            'schedule': valve1_schedule
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/valve1/schedule', methods=['GET'])
def get_valve1_schedule():
    return jsonify(valve1_schedule)

@app.route('/api/valve2/schedule', methods=['POST'])
def set_valve2_schedule():
    data = request.get_json()
    
    # Update schedule settings
    valve2_schedule['enabled'] = data.get('enabled', False)
    if 'time' in data:
        valve2_schedule['time'] = data['time']
    if 'duration' in data:
        valve2_schedule['duration'] = data['duration']
    
    try:
        schedule_valve(2)
        return jsonify({
            'success': True,
            'schedule': valve2_schedule
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/valve2/schedule', methods=['GET'])
def get_valve2_schedule():
    return jsonify(valve2_schedule)

def schedule_irrigation(start_time, duration_minutes):
    # Parse start time
    hour, minute = map(int, start_time.split(':'))
    now = datetime.now()
    schedule_time = now.replace(hour=hour, minute=minute, second=0)
    
    # If the time has already passed today, schedule for tomorrow
    if schedule_time < now:
        schedule_time += timedelta(days=1)
    
    # Schedule the irrigation
    scheduler.add_job(
        func=automatic_irrigation,
        trigger='cron',
        hour=hour,
        minute=minute,
        args=[duration_minutes]
    )

def automatic_irrigation(duration_minutes):
    # Turn on both irrigation relays (1 and 2)
    for relay_num in [1, 2]:
        gpio.turn_on_relay(relay_num)
    
    # Schedule turn off after duration
    scheduler.add_job(
        func=lambda: [gpio.turn_off_relay(relay_num) for relay_num in [1, 2]],
        trigger='date',
        run_date=datetime.now() + timedelta(minutes=duration_minutes)
    )

if __name__ == '__main__':
    try:
        # Initialize GPIO
        if not gpio.init_gpio():
            print("Failed to initialize GPIO. Exiting.")
            sys.exit(1)
            
        # Initialize all schedules on startup
        schedule_light()
        schedule_light2()
        schedule_valve(1)
        schedule_valve(2)
        
        # Start the server
        app.run(host='0.0.0.0', port=5000)
    except Exception as e:
        print(f"Fatal error: {str(e)}")
    finally:
        print("Cleaning up GPIO")
        gpio.cleanup()
