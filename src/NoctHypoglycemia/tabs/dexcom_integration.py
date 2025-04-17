import asyncio
import datetime
import threading
import time
from pathlib import Path

import numpy as np
from pydexcom import Dexcom

# Import the Kalman filter utilities
from ..utils.kalman_filter import multi_horizon_prediction
from ..utils.protocols import check_glucose_predictions


# Global state for Dexcom session
class DexcomSessionState:
    def __init__(self):
        self.active = False
        self.thread = None
        self.dexcom_client = None
        self.username = ""
        self.password = ""
        self.account_id = None
        self.interval_seconds = 300  # 5 minutes between readings


# Create a global instance
dexcom_session = DexcomSessionState()


def start_dexcom_session(app, sim_state, username, password):
    """
    Start a new Dexcom CGM session that updates the simulation state
    with real Dexcom G7 data.

    Args:
        app: The Toga application instance
        sim_state: The global simulation state
        username: Dexcom account username
        password: Dexcom account password
    """
    global dexcom_session

    # Don't start if already active
    if dexcom_session.active:
        return False

    # Store credentials
    dexcom_session.username = username
    dexcom_session.password = password

    # Reset simulation state, but preserve certain properties
    # that the glucose.py page might need for display formatting
    current_time_range = getattr(sim_state, 'current_time_range', 4)  # Default to 4 hours if not set

    # Reset simulation state
    sim_state.times = []
    sim_state.glucose = []
    sim_state.kalman_filtered = []
    sim_state.kalman_prediction_times = []
    sim_state.kalman_predictions = []
    sim_state.all_prediction_times = []
    sim_state.all_predictions = []
    sim_state.current_index = 0

    # Restore any properties we saved
    sim_state.current_time_range = current_time_range

    # Critical: Set active flag to true to trigger UI updates in glucose.py
    sim_state.active = True

    # Set Dexcom session to active
    dexcom_session.active = True

    # Start thread for Dexcom data fetching
    if not dexcom_session.thread or not dexcom_session.thread.is_alive():
        dexcom_session.thread = threading.Thread(
            target=run_dexcom_session,
            args=(app, sim_state),
            daemon=True
        )
        dexcom_session.thread.start()

    # Notify the app that we're starting a CGM session
    try:
        app.main_window.info_dialog(
            'CGM Session Started',
            'Dexcom CGM session has been started. Glucose data will update approximately every 5 minutes.'
        )
    except Exception as e:
        print(f"Could not show dialog: {e}")

    print("Dexcom CGM session started successfully")
    return True


def stop_dexcom_session(sim_state):
    """Stop the Dexcom CGM session."""
    global dexcom_session

    dexcom_session.active = False
    sim_state.active = False

    if dexcom_session.thread and dexcom_session.thread.is_alive():
        dexcom_session.thread.join(timeout=0.5)  # Give time to cleanly exit

    return True


def run_dexcom_session(app, sim_state):
    """
    Background thread function that fetches data from Dexcom
    and updates the simulation state.
    """
    global dexcom_session

    # Import the connection_state from connections.py to get credentials
    from ..tabs.connections import connection_state

    # Create Dexcom client - use the already established connection if available
    try:
        if connection_state.dexcom_client and connection_state.dexcom_connected:
            print("Using existing Dexcom connection from ConnectionState")
            dexcom_session.dexcom_client = connection_state.dexcom_client
        else:
            # If no existing connection, create a new one using the stored credentials
            username = dexcom_session.username
            password = dexcom_session.password

            if username and password:
                if '@' in username:
                    # Looks like an email address
                    print(f"Connecting to Dexcom with email: {username}")
                    dexcom_session.dexcom_client = Dexcom(username=username, password=password)
                elif username.startswith('+'):
                    # Looks like a phone number with country code
                    print(f"Connecting to Dexcom with phone: {username}")
                    dexcom_session.dexcom_client = Dexcom(username=username, password=password)
                elif '-' in username:
                    # Looks like an account ID
                    print(f"Connecting to Dexcom with account ID: {username}")
                    dexcom_session.dexcom_client = Dexcom(account_id=username, password=password)
                else:
                    # Default to username
                    print(f"Connecting to Dexcom with username: {username}")
                    dexcom_session.dexcom_client = Dexcom(username=username, password=password)
            else:
                print("No Dexcom credentials provided")
                dexcom_session.active = False
                sim_state.active = False
                return

        # Test the connection with a reading
        test_reading = dexcom_session.dexcom_client.get_current_glucose_reading()
        if test_reading:
            print(f"Successfully connected to Dexcom. Current reading: {test_reading.value} mg/dL")

            # Immediately add the first reading to kickstart the display
            current_time = test_reading.datetime
            current_glucose = test_reading.value

            # Make sure we have valid data
            if current_time and current_glucose:
                # Add initial reading
                sim_state.times.append(current_time)
                sim_state.glucose.append(current_glucose)
                sim_state.current_index = 1  # Critical: increment index to trigger UI update

                print(f"Added first Dexcom reading: {current_glucose} mg/dL at {current_time}")
                print(f"Initial data point count: {len(sim_state.times)}, Current index: {sim_state.current_index}")

                # Apply Kalman filter for the initial point
                try:
                    interval_minutes = 5
                    predict_steps = 1

                    # Apply Kalman filter and get predictions
                    glucose_array = np.array(sim_state.glucose)
                    filtered_values, future_predictions, future_minutes = multi_horizon_prediction(
                        glucose_array,
                        predict_steps=predict_steps,
                        interval_minutes=interval_minutes
                    )

                    # Update Kalman filtered data
                    sim_state.kalman_filtered = filtered_values

                    # Create future prediction times
                    prediction_times = []
                    for mins in future_minutes:
                        minutes_value = int(mins) if hasattr(mins, 'item') else mins
                        prediction_times.append(current_time + datetime.timedelta(minutes=minutes_value))

                    # Update prediction arrays
                    sim_state.kalman_prediction_times = prediction_times
                    sim_state.kalman_predictions = future_predictions
                    sim_state.last_prediction_time = current_time

                    # Add current predictions to historical records (for trail effect)
                    for i, pred_time in enumerate(prediction_times):
                        if i < len(future_predictions):
                            sim_state.all_prediction_times.append(pred_time)
                            sim_state.all_predictions.append(future_predictions[i])

                    print("Initial Kalman filtering complete")
                except Exception as e:
                    print(f"Error applying initial Kalman filter: {e}")
                    import traceback
                    traceback.print_exc()

        else:
            print("Connected to Dexcom but no readings available")

    except Exception as e:
        print(f"Failed to connect to Dexcom: {str(e)}")
        import traceback
        traceback.print_exc()
        dexcom_session.active = False
        sim_state.active = False
        return

    # Initialize prediction parameters
    interval_minutes = 5  # Dexcom readings are typically every 5 minutes
    predict_steps = 1  # Predict 20 minutes ahead (4 x 5min)

    # Set previous reading time to track new readings
    previous_reading_time = sim_state.times[-1] if sim_state.times else None

    # For debugging - track how many times we try to get new readings
    check_count = 0
    last_new_reading_time = datetime.datetime.now()

    # Main loop for fetching Dexcom data
    while dexcom_session.active and sim_state.active:
        try:
            check_count += 1
            print(f"Checking for new Dexcom reading (attempt #{check_count})...")

            # Get current glucose reading from Dexcom
            # Force a fresh reading by setting max_count=1 and minutes=10
            bg_reading = dexcom_session.dexcom_client.get_current_glucose_reading()

            if bg_reading:
                # Extract glucose value and timestamp
                current_glucose = bg_reading.value
                current_time = bg_reading.datetime

                print(f"Got reading: {current_glucose} mg/dL at {current_time}")
                print(f"Previous reading time: {previous_reading_time}")

                # Check if we have a new reading
                if previous_reading_time is None or current_time > previous_reading_time:
                    last_new_reading_time = datetime.datetime.now()
                    previous_reading_time = current_time

                    # Add to simulation state
                    sim_state.times.append(current_time)
                    sim_state.glucose.append(current_glucose)
                    sim_state.current_index += 1  # Critical: increment index to trigger UI update

                    print(f"Added new Dexcom reading: {current_glucose} mg/dL at {current_time}")
                    print(f"Total readings: {len(sim_state.times)}, Current index: {sim_state.current_index}")

                    # Apply Kalman filter and get predictions
                    glucose_array = np.array(sim_state.glucose)
                    filtered_values, future_predictions, future_minutes = multi_horizon_prediction(
                        glucose_array,
                        predict_steps=predict_steps,
                        interval_minutes=interval_minutes
                    )

                    # Update Kalman filtered data
                    sim_state.kalman_filtered = filtered_values

                    # Create future prediction times
                    prediction_times = []
                    for mins in future_minutes:
                        minutes_value = int(mins) if hasattr(mins, 'item') else mins
                        prediction_times.append(current_time + datetime.timedelta(minutes=minutes_value))

                    # Update prediction arrays
                    sim_state.kalman_prediction_times = prediction_times
                    sim_state.kalman_predictions = future_predictions
                    sim_state.last_prediction_time = current_time

                    # Add current predictions to historical records (for trail effect)
                    for i, pred_time in enumerate(prediction_times):
                        if i < len(future_predictions):
                            sim_state.all_prediction_times.append(pred_time)
                            sim_state.all_predictions.append(future_predictions[i])

                    # Get the username for notifications
                    username = "Patient"
                    if hasattr(app, 'remembered_login') and app.remembered_login:
                        if 'patient_id' in app.remembered_login:
                            username = app.remembered_login['patient_id']

                    # Check glucose protocols
                    try:
                        check_glucose_predictions(
                            app,
                            prediction_times,
                            future_predictions,
                            current_glucose=current_glucose,
                            username=username
                        )
                    except Exception as e:
                        print(f"Error checking glucose protocols: {e}")
                else:
                    # If no new reading, check how long we've been without one
                    time_since_new = datetime.datetime.now() - last_new_reading_time
                    print(f"No new reading available (same as previous: {current_time})")
                    print(f"Time since last new reading: {time_since_new.total_seconds()} seconds")

                    # If it's been more than 20 minutes without a new reading, try to reconnect
                    if time_since_new.total_seconds() > 1200:  # 20 minutes
                        print("No new readings for 20 minutes, attempting to reconnect...")
                        # Try to get a fresh connection
                        dexcom_session.dexcom_client = Dexcom(
                            username=dexcom_session.username,
                            password=dexcom_session.password
                        )
                        last_new_reading_time = datetime.datetime.now()  # Reset timer
            else:
                print("No current reading available from Dexcom")

        except Exception as e:
            print(f"Error fetching Dexcom data: {e}")
            import traceback
            traceback.print_exc()

        # Wait before checking again
        # Use a shorter interval for more responsive updates
        print(f"Waiting {dexcom_session.interval_seconds // 5} seconds before next check...")
        time.sleep(dexcom_session.interval_seconds // 5)  # Check twice as often

    # Session complete or stopped
    dexcom_session.active = False
    print("Dexcom session ended")