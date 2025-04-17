import threading
import time
import traceback
import winsound  # For Windows alarm sounds
import datetime


# Protocol states - one for each type of protocol
class ProtocolState:
    def __init__(self):
        self.active = False
        self.lock = threading.Lock()  # Thread safety
        self.predicted_value = None  # Store the predicted value for display
        self.alarm_thread = None  # Thread for alarm sound
        self.alarm_start_time = None  # Track when alarm started
        self.sms_sent = False  # Track if SMS was sent


# Create separate states for each protocol type
severe_hypo_state = ProtocolState()  # For severe hypoglycemia
mild_hypo_state = ProtocolState()  # For mild hypoglycemia
hyper_state = ProtocolState()  # For hyperglycemia
hyper_state.initial_check_complete = False  # Track if we've checked initial data


# =============================================================================
# Utility Functions
# =============================================================================

def send_emergency_sms(username, glucose_value, message_type="hyperglycemia"):
    """Send SMS to emergency contact."""
    current_time = datetime.datetime.now().strftime("%I:%M %p")

    # Create message based on type
    if message_type == "hyperglycemia":
        message = f"ALERT: {username} has a predicted hyperglycemia event. Glucose value: {glucose_value} mg/dL at {current_time}."
    elif message_type == "mild_hypoglycemia":
        message = f"ALERT: {username} has a predicted mild hypoglycemia event. Glucose value: {glucose_value} mg/dL at {current_time}. Recommend 15g carbohydrates."
    elif message_type == "severe_hypoglycemia":
        message = f"URGENT ALERT: {username} has a predicted severe hypoglycemia event. Glucose value: {glucose_value} mg/dL at {current_time}. Emergency assistance may be needed."

    print(f"Sending SMS: {message}")

    # Here you would implement actual SMS sending logic
    # This could use Twilio, email-to-SMS gateway, or other service

    # For now we'll just print it
    print(f"Would send SMS for {message_type}: {glucose_value} mg/dL to emergency contacts for {username}")
    return True


def play_alarm(duration_minutes, frequency=750, duration_ms=500, interval_ms=500):
    """Play an alarm sound for the specified duration.

    Args:
        duration_minutes: How long to play the alarm in minutes
        frequency: Tone frequency in Hz
        duration_ms: Duration of each beep in milliseconds
        interval_ms: Interval between beeps in milliseconds
    """
    end_time = time.time() + (duration_minutes * 60)

    # Get the state that's currently active to check if we should stop
    active_state = None
    if severe_hypo_state.active:
        active_state = severe_hypo_state
    elif mild_hypo_state.active:
        active_state = mild_hypo_state
    elif hyper_state.active:
        active_state = hyper_state

    if not active_state:
        return

    # Play sound until duration is up or protocol is deactivated
    while time.time() < end_time and active_state.active:
        try:
            winsound.Beep(frequency, duration_ms)
            time.sleep(interval_ms / 1000)
        except Exception as e:
            print(f"Error playing alarm sound: {e}")
            break


def start_alarm(state, duration_minutes):
    """Start an alarm in a background thread."""
    if state.alarm_thread and state.alarm_thread.is_alive():
        return  # Alarm already running

    # Record alarm start time
    state.alarm_start_time = time.time()

    # Start alarm in background thread
    state.alarm_thread = threading.Thread(
        target=play_alarm,
        args=(duration_minutes,),
        daemon=True
    )
    state.alarm_thread.start()


def control_arduino_motor(app, start=True):
    """Control the Arduino motor for insulin/glucagon delivery.

    Args:
        app: The application instance to access Arduino connection
        start: True to start the motor, False to stop it
    """
    # Check if Arduino connection exists
    if not hasattr(app, 'arduino_connection') or not app.arduino_connection:
        print("No Arduino connection established")
        return False

    try:
        if start:
            # Send command to start motor
            app.arduino_connection.write(b'START_MOTOR\n')
            print("Started Arduino motor for emergency treatment")
        else:
            # Send command to stop motor
            app.arduino_connection.write(b'STOP_MOTOR\n')
            print("Stopped Arduino motor")

        return True
    except Exception as e:
        print(f"Error controlling Arduino motor: {e}")
        return False


# =============================================================================
# Hyperglycemia Protocol
# =============================================================================

def activate_hyperglycemia_protocol(app, predicted_value, username="Patient"):
    """Activate the hyperglycemia state with 5-minute alarm."""
    # Don't start multiple protocols at once
    if hyper_state.active:
        return False

    # Set active state and store predicted value
    with hyper_state.lock:
        hyper_state.active = True
        hyper_state.predicted_value = predicted_value
        hyper_state.sms_sent = False

    # Start alarm for 5 minutes
    start_alarm(hyper_state, 5)

    # Send SMS if not already sent
    if not hyper_state.sms_sent:
        send_emergency_sms(username, predicted_value, "hyperglycemia")
        hyper_state.sms_sent = True

    print(f"HYPERGLYCEMIA PROTOCOL ACTIVATED: {predicted_value} mg/dL")
    return True


def stop_hyperglycemia_protocol():
    """Stop the hyperglycemia protocol."""
    with hyper_state.lock:
        hyper_state.active = False
        hyper_state.predicted_value = None
        hyper_state.sms_sent = False
    print("Hyperglycemia protocol stopped")


def check_prediction_for_hyperglycemia(app, prediction_times, predictions, hyperglycemia_threshold,
                                       current_glucose=None, username="Patient"):
    """Check if any predicted values exceed the hyperglycemia threshold."""
    # Don't check again if protocol is already active
    if hyper_state.active:
        return False

    # Handle initial dataset check
    if not hyper_state.initial_check_complete and current_glucose is not None:
        # If the dataset starts in hyperglycemia, mark as checked but don't trigger alarm
        if current_glucose >= hyperglycemia_threshold:
            hyper_state.initial_check_complete = True
            print(f"Initial glucose already in hyperglycemia ({current_glucose}). Not triggering protocol.")
            return False
        else:
            # Dataset doesn't start in hyperglycemia, mark as checked
            hyper_state.initial_check_complete = True

    # Check if any prediction exceeds the hyperglycemia threshold
    for i, value in enumerate(predictions):
        # Only trigger if we're not already in hyperglycemia state
        if (current_glucose is None or current_glucose < hyperglycemia_threshold) and value >= hyperglycemia_threshold:
            print(f"HYPERGLYCEMIA PREDICTED! Current: {current_glucose}, Predicted: {value}")
            # Found a prediction above threshold, activate protocol
            return activate_hyperglycemia_protocol(app, value, username)

    return False


# =============================================================================
# Mild Hypoglycemia Protocol
# =============================================================================

def activate_mild_hypo_protocol(app, predicted_value, username="Patient"):
    """Activate the mild hypoglycemia state with 5-minute alarm."""
    # Don't start multiple protocols at once
    if mild_hypo_state.active:
        return False

    # Set active state and store predicted value
    with mild_hypo_state.lock:
        mild_hypo_state.active = True
        mild_hypo_state.predicted_value = predicted_value
        mild_hypo_state.sms_sent = False

    # Start alarm for 5 minutes
    start_alarm(mild_hypo_state, 5)

    # Send SMS if not already sent
    if not mild_hypo_state.sms_sent:
        send_emergency_sms(username, predicted_value, "mild_hypoglycemia")
        mild_hypo_state.sms_sent = True

    print(f"MILD HYPOGLYCEMIA PROTOCOL ACTIVATED: {predicted_value} mg/dL")
    return True


def stop_mild_hypo_protocol():
    """Stop the mild hypoglycemia protocol."""
    with mild_hypo_state.lock:
        mild_hypo_state.active = False
        mild_hypo_state.predicted_value = None
        mild_hypo_state.sms_sent = False
    print("Mild hypoglycemia protocol stopped")


def check_prediction_for_mild_hypoglycemia(app, prediction_times, predictions, mild_threshold, severe_threshold,
                                           username="Patient"):
    """Check if any predicted values fall within mild hypoglycemia range."""
    if mild_hypo_state.active or severe_hypo_state.active:
        return False  # Don't activate if already running a hypoglycemia protocol

    # Check if any prediction falls within mild hypoglycemia range
    for i, value in enumerate(predictions):
        if severe_threshold < value <= mild_threshold:  # Between severe and mild thresholds
            # Found a prediction in mild hypo range
            print(f"MILD HYPOGLYCEMIA PREDICTED! Value: {value}, Threshold: {mild_threshold}")
            return activate_mild_hypo_protocol(app, value, username)

    return False


# =============================================================================
# Severe Hypoglycemia Protocol
# =============================================================================

def activate_severe_hypo_protocol(app, predicted_value, username="Patient"):
    """Activate the severe hypoglycemia state with 15-minute alarm and Arduino control."""
    # Don't start multiple protocols at once
    if severe_hypo_state.active:
        return False

    # Set active state and store predicted value
    with severe_hypo_state.lock:
        severe_hypo_state.active = True
        severe_hypo_state.predicted_value = predicted_value
        severe_hypo_state.sms_sent = False

    # Start alarm for 15 minutes (longer for severe events)
    start_alarm(severe_hypo_state, 15)

    # Send SMS if not already sent
    if not severe_hypo_state.sms_sent:
        send_emergency_sms(username, predicted_value, "severe_hypoglycemia")
        severe_hypo_state.sms_sent = True

    # Start Arduino motor if connected
    control_arduino_motor(app, start=True)

    print(f"SEVERE HYPOGLYCEMIA PROTOCOL ACTIVATED: {predicted_value} mg/dL")
    return True


def check_prediction_for_severe_hypoglycemia(app, prediction_times, predictions, severe_threshold, username="Patient"):
    """Check if any predicted values fall below the severe hypoglycemia threshold."""
    if severe_hypo_state.active:
        return False  # Don't activate if already running

    # Check if any prediction falls below the severe threshold
    for i, value in enumerate(predictions):
        if value <= severe_threshold:
            # Found a prediction below threshold, activate protocol
            print(f"SEVERE HYPOGLYCEMIA PREDICTED! Value: {value}, Threshold: {severe_threshold}")
            return activate_severe_hypo_protocol(app, value, username)

    return False


def stop_severe_hypo_protocol(app=None):
    """Stop the severe hypoglycemia protocol and Arduino motor."""
    with severe_hypo_state.lock:
        severe_hypo_state.active = False
        severe_hypo_state.predicted_value = None
        severe_hypo_state.sms_sent = False

    # Stop Arduino motor if app reference is provided
    if app:
        control_arduino_motor(app, start=False)

    print("Severe hypoglycemia protocol stopped")


# =============================================================================
# Main Prediction Check Function
# =============================================================================

def check_glucose_predictions(app, prediction_times, predictions, current_glucose=None, username="Patient"):
    """Check all glucose predictions against all thresholds."""
    results = {
        "severe_hypo": False,
        "mild_hypo": False,
        "hyper": False
    }

    try:
        # Get thresholds from app settings
        hyperglycemia_threshold = int(app.settings.get('hyperglycemia_threshold', 180))
        mild_hypoglycemia_threshold = int(app.settings.get('hypoglycemia_threshold', 70))
        severe_hypoglycemia_threshold = int(app.settings.get('severe_hypoglycemia_threshold', 54))

        # Check for severe hypoglycemia first (highest priority)
        results["severe_hypo"] = check_prediction_for_severe_hypoglycemia(
            app, prediction_times, predictions, severe_hypoglycemia_threshold, username
        )

        # If severe hypoglycemia not detected, check for mild hypoglycemia
        if not results["severe_hypo"]:
            results["mild_hypo"] = check_prediction_for_mild_hypoglycemia(
                app, prediction_times, predictions,
                mild_hypoglycemia_threshold, severe_hypoglycemia_threshold,
                username
            )

        # Check for hyperglycemia (can happen independently of hypoglycemia checks)
        results["hyper"] = check_prediction_for_hyperglycemia(
            app, prediction_times, predictions, hyperglycemia_threshold,
            current_glucose, username
        )

    except Exception as e:
        print(f"Error checking glucose predictions: {e}")
        traceback.print_exc()

    return results