import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER, RIGHT, LEFT
import datetime
import threading
import time
import math
import asyncio
import numpy as np
import requests
from pathlib import Path
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# Import the Toga Chart widget and LineSeries class.
from toga_chart import Chart
from toga_chart.line import LineSeries

# Import Kalman filter utilities
from ..utils.kalman_filter import multi_horizon_prediction, OPTIMAL_Q, OPTIMAL_R, OPTIMAL_P0
from ..utils.protocols import severe_hypo_state as protocol_state, stop_severe_hypo_protocol as stop_protocol

# Import BLE connection state from connections.py
from .connections import connection_state, MOTOR_CHARACTERISTIC_UUID
from ..utils.constants import TEXTBELT_API_KEY, EMERGENCY_PHONE_NUMBER

# Colors for different glucose status categories
HYPERGLYCEMIA_COLOR = 'darkorange'
MILD_HYPOGLYCEMIA_COLOR = 'goldenrod'
SEVERE_HYPOGLYCEMIA_COLOR = 'darkblue'
INVALID_COLOR = '#8B0000'  # Dark red
NORMAL_COLOR = 'green'  # For "Safe Range" status

# -------------------------------
# Access the shared simulation state from history.py
# -------------------------------
from .history import sim_state

# -------------------------------
# Global variables to track glucose display widgets
# -------------------------------
glucose_value_label = None
sample_time_label = None
glucose_status_label = None
avg_glucose_value_label = None
gmi_value_label = None
scroll_container = None
app_instance = None  # Store app instance for getting settings
glucagon_delivery_status = None  # Label to show glucagon delivery status
glucagon_button = None  # Store reference to glucagon button
delivery_in_progress = False  # Flag to prevent multiple simultaneous deliveries


async def send_emergency_sms(app):
    """Send a single emergency SMS message with the text 'Test Text' using Text Belt."""
    try:
        # First show a confirmation dialog
        dialog_result = await app.main_window.dialog(
            toga.ConfirmDialog(
                title='Confirm Emergency Contact',
                message='Are you sure you want to notify your emergency contact?'
            )
        )

        # Only proceed if confirmed
        if dialog_result is True:
            # Get emergency contact from settings
            emergency_contact = app.settings.get('emergency_contact', EMERGENCY_PHONE_NUMBER)

            # Prepare the request data
            data = {
                'phone': emergency_contact,
                'message': 'Test Text',
                'key': TEXTBELT_API_KEY
            }

            # Send the request to Text Belt API
            response = requests.post('https://textbelt.com/text', data=data)

            # Check if the message was sent successfully
            result = response.json()
            if result.get('success'):
                print("SMS sent successfully, textId:", result.get('textId'))
                await app.main_window.dialog(
                    toga.InfoDialog(
                        title='Message Sent',
                        message='Emergency message sent successfully!'
                    )
                )
            else:
                print("Error sending SMS:", result.get('error'))
                await app.main_window.dialog(
                    toga.InfoDialog(
                        title='Error',
                        message=f'Error sending message: {result.get("error")}'
                    )
                )
    except Exception as e:
        print("Error sending SMS:", e)
        await app.main_window.dialog(
            toga.InfoDialog(
                title='Error',
                message=f'Error sending message: {str(e)}'
            )
        )


def prepare_update_data():
    """Prepare all the data needed for a UI update."""
    if not sim_state.times or len(sim_state.times) == 0:
        return None

    try:
        # Get the current values
        current_time = sim_state.times[-1]
        current_glucose = sim_state.glucose[-1]

        # Calculate metrics
        avg_glucose, gmi = calculate_hourly_metrics(sim_state.times, sim_state.glucose)

        # Get thresholds for status
        if app_instance:
            try:
                hyperglycemia_threshold = int(app_instance.settings.get('hyperglycemia_threshold', 180))
                mild_hypoglycemia_threshold = int(app_instance.settings.get('hypoglycemia_threshold', 70))
                severe_hypoglycemia_threshold = int(app_instance.settings.get('severe_hypoglycemia_threshold', 54))
            except (ValueError, TypeError):
                hyperglycemia_threshold = 180
                mild_hypoglycemia_threshold = 70
                severe_hypoglycemia_threshold = 54
        else:
            hyperglycemia_threshold = 180
            mild_hypoglycemia_threshold = 70
            severe_hypoglycemia_threshold = 54

        # Calculate status
        if current_glucose < 40 or current_glucose > 400:
            status = "Invalid"
            status_color = INVALID_COLOR
        elif current_glucose < severe_hypoglycemia_threshold:
            status = "Severe Hypoglycemia"
            status_color = SEVERE_HYPOGLYCEMIA_COLOR
        elif current_glucose < mild_hypoglycemia_threshold:
            status = "Mild Hypoglycemia"
            status_color = MILD_HYPOGLYCEMIA_COLOR
        elif current_glucose > hyperglycemia_threshold:
            status = "Hyperglycemia"
            status_color = HYPERGLYCEMIA_COLOR
        else:
            status = "Safe Range"  # Changed from "Normal" to "Safe Range"
            status_color = NORMAL_COLOR

        # Format time
        time_str = current_time.strftime('%I:%M %p')

        # Format values
        glucose_str = str(int(current_glucose))
        avg_glucose_str = str(int(round(avg_glucose))) if avg_glucose is not None else ""
        gmi_str = f"{gmi:.1f}" if gmi is not None else ""

        # Return all data as a dictionary
        return {
            'glucose': glucose_str,
            'time': time_str,
            'status': status,
            'status_color': status_color,
            'avg_glucose': avg_glucose_str,
            'gmi': gmi_str
        }

    except Exception as e:
        print(f"Error preparing update data: {e}")
        return None


def update_ui_with_data(data):
    """Update the UI with prepared data - runs in the main thread."""
    if not data:
        return

    try:
        # Update glucose value - only if changed
        if glucose_value_label and glucose_value_label.text != data['glucose']:
            glucose_value_label.text = data['glucose']

        # Update time - only if changed
        if sample_time_label and sample_time_label.text != data['time']:
            sample_time_label.text = data['time']

        # Update status - only if changed
        if glucose_status_label and (glucose_status_label.text != data['status'] or
                                     glucose_status_label.style.color != data['status_color']):
            glucose_status_label.text = data['status']
            glucose_status_label.style.color = data['status_color']

        # Update metrics - only if changed
        if avg_glucose_value_label and avg_glucose_value_label.text != data['avg_glucose']:
            avg_glucose_value_label.text = data['avg_glucose']

        if gmi_value_label and gmi_value_label.text != data['gmi']:
            gmi_value_label.text = data['gmi']

    except Exception as e:
        print(f"Error updating UI: {e}")


def calculate_hourly_metrics(times, glucose_values):
    """Calculate hourly average glucose and GMI.
    GMI formula: 3.31 + 0.02392 × mean glucose (mg/dL)
    """
    if not times or not glucose_values or len(times) == 0:
        return None, None
    current_time = times[-1]
    one_hour_ago = current_time - datetime.timedelta(hours=1)
    hourly_glucose = []
    for i, t in enumerate(times):
        if t >= one_hour_ago and i < len(glucose_values):
            hourly_glucose.append(glucose_values[i])
    if not hourly_glucose:
        return None, None
    avg_glucose = np.mean(hourly_glucose)
    gmi = 3.31 + (0.02392 * avg_glucose)
    return avg_glucose, gmi


def start_update_timer():
    """Start a thread to periodically check for updates."""
    update_thread = threading.Thread(target=update_loop, daemon=True)
    update_thread.start()


def update_loop():
    """Monitor simulation state and trigger updates via the main UI thread's handler."""
    last_index = -1

    while True:
        # Only update when we have new data
        if sim_state.active and sim_state.current_index > 0 and sim_state.current_index != last_index:
            last_index = sim_state.current_index

            # Instead of trying to update directly, queue an update through Toga
            if app_instance:
                app_instance.on_exit = lambda: None  # Suppress warnings about exit handler
                app_instance.main_window.on_close = lambda _: None  # Suppress warnings

                # This schedules the update in the main thread safely
                try:
                    # Prepare the data for the update
                    data = prepare_update_data()
                    if data:
                        # Use main thread's app.loop.call_soon to schedule the update
                        app_instance.loop.call_soon_threadsafe(lambda: update_ui_with_data(data))
                except Exception as e:
                    print(f"Error scheduling update: {e}")

        # Sleep a bit to avoid CPU hogging - increased to reduce UI interference
        time.sleep(2.0)


async def monitor_pump_connection(app):
    """Background task to update pump connection status and button state."""
    global glucagon_button, glucagon_delivery_status

    # Wait a bit for UI to initialize
    await asyncio.sleep(1)

    # Find the pump status label only once at startup
    pump_status_label = None
    try:
        if scroll_container and scroll_container.content:
            for widget in scroll_container.content.children:
                if isinstance(widget, toga.Box) and hasattr(widget, 'children'):
                    for box in widget.children:
                        if isinstance(box, toga.Box) and hasattr(box, 'children'):
                            for row in box.children:
                                if isinstance(row, toga.Box) and hasattr(row, 'children'):
                                    for label in row.children:
                                        if isinstance(label, toga.Label) and label.text == "Pump Status:":
                                            # The next sibling should be the status value
                                            if len(row.children) > 1:
                                                pump_status_label = row.children[1]
    except Exception as e:
        print(f"Error finding pump status label: {e}")

    last_connection_state = None
    last_protocol_state = None

    while True:
        try:
            # Update UI if connection state has changed
            connection_changed = connection_state.is_connected != last_connection_state
            protocol_changed = protocol_state.active != last_protocol_state

            if connection_changed or protocol_changed:
                last_connection_state = connection_state.is_connected
                last_protocol_state = protocol_state.active

                # Update pump connection status if label was found
                if pump_status_label:
                    try:
                        if connection_state.is_connected:
                            pump_status_label.text = "Connected"
                            pump_status_label.style.color = "green"
                        else:
                            pump_status_label.text = "Not Connected"
                            pump_status_label.style.color = "red"
                    except Exception as e:
                        print(f"Error updating pump status: {e}")

                # Update glucagon button state
                if glucagon_button:
                    try:
                        # Button should be enabled only if:
                        # 1. Pump is connected AND
                        # 2. No delivery is in progress AND
                        # 3. No automatic protocol is active
                        glucagon_button.enabled = (
                                connection_state.is_connected and
                                not delivery_in_progress and
                                not protocol_state.active
                        )
                    except Exception as e:
                        print(f"Error updating button state: {e}")

                # Update status if protocol is active
                if protocol_state.active and glucagon_delivery_status:
                    try:
                        glucagon_delivery_status.text = "Automatic protocol active"
                        glucagon_delivery_status.style.color = "blue"
                    except Exception as e:
                        print(f"Error updating status label: {e}")

        except Exception as e:
            print(f"Error in monitor_pump_connection: {e}")

        # Wait before checking again - longer interval reduces UI interference
        await asyncio.sleep(2)


async def control_motor_delivery(app, dose):
    """Control the motor to deliver glucagon."""
    global delivery_in_progress, glucagon_delivery_status, glucagon_button

    try:
        # Update status
        if glucagon_delivery_status:
            glucagon_delivery_status.text = "Starting motor..."
            glucagon_delivery_status.style.color = "blue"

        # Send command to start motor
        await connection_state.client.write_gatt_char(
            MOTOR_CHARACTERISTIC_UUID,
            "START".encode()
        )

        # Update status during delivery
        if glucagon_delivery_status:
            glucagon_delivery_status.text = "Delivering glucagon..."
            glucagon_delivery_status.style.color = "blue"

        # Wait 5 seconds while motor runs
        await asyncio.sleep(5)

        # Delivery complete
        if glucagon_delivery_status:
            glucagon_delivery_status.text = f"Delivered {dose} mL successfully"
            glucagon_delivery_status.style.color = "green"

        # Show success dialog
        await app.main_window.dialog(
            toga.InfoDialog(
                title='Glucagon Delivered',
                message=f'{dose} mL of glucagon has been delivered.'
            )
        )
        print(f"Delivered {dose} mL of glucagon")

    except Exception as e:
        error_message = f"Delivery error: {str(e)}"
        print(error_message)

        if glucagon_delivery_status:
            glucagon_delivery_status.text = "Delivery failed"
            glucagon_delivery_status.style.color = "red"

        await app.main_window.dialog(
            toga.InfoDialog(
                title='Error',
                message=f'Could not deliver glucagon: {str(e)}'
            )
        )

    finally:
        # Reset delivery state
        delivery_in_progress = False
        if glucagon_button and connection_state.is_connected:
            glucagon_button.enabled = True


async def deliver_glucagon(app):
    """Handle the deliver glucagon button press."""
    global delivery_in_progress, glucagon_delivery_status, glucagon_button

    # Check if automatic protocol is running
    if protocol_state.active:
        await app.main_window.dialog(
            toga.InfoDialog(
                title='Protocol Active',
                message='Automatic hypoglycemia protocol is already running. Please use its controls.'
            )
        )
        return

    # Check if pump is connected
    if not connection_state.is_connected or not connection_state.client:
        await app.main_window.dialog(
            toga.InfoDialog(
                title='Error',
                message='Pump is not connected. Please connect the pump first in the Connections tab.'
            )
        )
        return

    # Prevent multiple simultaneous deliveries
    if delivery_in_progress:
        return

    glucagon_dose = app.settings.get('glucagon_dosage', '0.5')
    try:
        dialog_result = await app.main_window.dialog(
            toga.ConfirmDialog(
                title='Confirm Glucagon Delivery',
                message=f'Are you sure you want to deliver {glucagon_dose} mL of glucagon?'
            )
        )

        if dialog_result is True:  # Use direct comparison instead of implicit bool check
            delivery_in_progress = True
            glucagon_button.enabled = False
            glucagon_delivery_status.text = "Starting delivery..."
            glucagon_delivery_status.style.color = "blue"

            # Create background task to control motor
            asyncio.create_task(control_motor_delivery(app, glucagon_dose))
    except Exception as e:
        print(f"Error in deliver_glucagon: {str(e)}")
        await app.main_window.dialog(
            toga.InfoDialog(
                title='Error',
                message=f'Could not deliver glucagon: {str(e)}'
            )
        )
        delivery_in_progress = False
        if glucagon_button:
            glucagon_button.enabled = connection_state.is_connected and not protocol_state.active
        if glucagon_delivery_status:
            glucagon_delivery_status.text = f"Error: {str(e)}"
            glucagon_delivery_status.style.color = "red"


def create_glucose_tab(app):
    """Create and populate the glucose tab content."""
    global glucose_value_label, sample_time_label, glucose_status_label, avg_glucose_value_label, gmi_value_label
    global scroll_container, app_instance, glucagon_delivery_status, glucagon_button

    # Store app reference for later
    app_instance = app

    # Create a scroll container with proper configuration
    scroll_container = toga.ScrollContainer(horizontal=False, style=Pack(flex=1))

    # Main content container - left-aligned headers
    main_content = toga.Box(style=Pack(
        direction=COLUMN,
        margin=10,
        background_color='#F0F0F0',
        align_items='start',
        flex=1
    ))

    # WIDGET 1: Current Blood Glucose
    current_glucose_widget = toga.Box(style=Pack(
        direction=COLUMN,
        margin=5,
        background_color='#F0F0F0',
        width=340,
        align_items='start'
    ))

    # Widget Header - left-aligned with very minimal spacing
    current_glucose_header = toga.Label(
        'Current Blood Glucose',
        style=Pack(
            font_size=18,
            font_weight='bold',
            text_align=LEFT,
            margin_bottom=0,  # Almost no spacing
            background_color='#F0F0F0'
        )
    )
    current_glucose_widget.add(current_glucose_header)

    # Content container - with a mix of alignments
    glucose_content = toga.Box(style=Pack(
        direction=COLUMN,
        margin=0,  # No margin
        background_color='#F0F0F0',
        align_items='start',
        width=340
    ))

    # White box container for centering
    glucose_box_container = toga.Box(style=Pack(
        direction=COLUMN,
        align_items=CENTER,  # Center the white box
        background_color='#F0F0F0',
        width=340
    ))

    # White box for glucose display - centered
    glucose_box = toga.Box(style=Pack(
        direction=COLUMN,
        align_items=CENTER,  # Center alignment for the glucose value itself
        background_color='white',
        margin=5,
        width=260,
        height=150
    ))

    # Glucose reading value
    glucose_value_label = toga.Label(
        "",  # Start blank until simulation begins
        style=Pack(
            font_size=60,
            font_weight='bold',
            text_align=CENTER,
            margin_bottom=2
        )
    )

    # Units label
    glucose_units = toga.Label(
        'mg/dL',
        style=Pack(
            font_size=22,
            text_align=CENTER
        )
    )

    glucose_box.add(glucose_value_label)
    glucose_box.add(glucose_units)
    glucose_box_container.add(glucose_box)
    glucose_content.add(glucose_box_container)

    # Last sample time - left-aligned with header
    sample_box = toga.Box(style=Pack(
        direction=ROW,
        margin=2,
        background_color='#F0F0F0',
        width=320,
        align_items='start'
    ))

    sample_label = toga.Label(
        'Last Sample Time:',
        style=Pack(
            font_size=14,
            font_weight='bold',
            text_align=LEFT,
            background_color='#F0F0F0',
            width=140
        )
    )

    sample_time_label = toga.Label(
        "",  # Start blank until simulation begins
        style=Pack(
            font_size=14,
            text_align=LEFT,
            background_color='#F0F0F0',
            width=180
        )
    )

    sample_box.add(sample_label)
    sample_box.add(sample_time_label)
    glucose_content.add(sample_box)

    # Glucose Status - left-aligned with header
    status_box = toga.Box(style=Pack(
        direction=ROW,
        margin=2,
        background_color='#F0F0F0',
        width=320,
        align_items='start'
    ))

    status_label = toga.Label(
        'Glucose Status:',
        style=Pack(
            font_size=14,
            font_weight='bold',
            text_align=LEFT,
            background_color='#F0F0F0',
            width=140
        )
    )

    glucose_status_label = toga.Label(
        'Safe Range',  # Changed from "Normal" to "Safe Range"
        style=Pack(
            font_size=14,
            text_align=LEFT,
            color=NORMAL_COLOR,
            background_color='#F0F0F0',
            width=180
        )
    )

    status_box.add(status_label)
    status_box.add(glucose_status_label)
    glucose_content.add(status_box)

    # Pump connection status - left-aligned with header
    pump_status_box = toga.Box(style=Pack(
        direction=ROW,
        margin=2,
        background_color='#F0F0F0',
        width=320,
        align_items='start'
    ))

    pump_status_label = toga.Label(
        'Pump Status:',
        style=Pack(
            font_size=14,
            font_weight='bold',
            text_align=LEFT,
            background_color='#F0F0F0',
            width=140
        )
    )

    pump_connection_status = toga.Label(
        'Not Connected',
        style=Pack(
            font_size=14,
            text_align=LEFT,
            color='red',
            background_color='#F0F0F0',
            width=180
        )
    )

    pump_status_box.add(pump_status_label)
    pump_status_box.add(pump_connection_status)
    glucose_content.add(pump_status_box)

    current_glucose_widget.add(glucose_content)
    main_content.add(current_glucose_widget)

    # Small spacer
    main_content.add(toga.Box(style=Pack(height=5, background_color='#F0F0F0')))

    # WIDGET 2: Manual Controls
    manual_controls_widget = toga.Box(style=Pack(
        direction=COLUMN,
        margin=5,
        background_color='#F0F0F0',
        width=340,
        align_items='start'
    ))

    # Widget Header - left-aligned with very minimal spacing
    manual_controls_header = toga.Label(
        'Manual Controls',
        style=Pack(
            font_size=18,
            font_weight='bold',
            text_align=LEFT,
            margin_bottom=0,  # Almost no spacing
            background_color='#F0F0F0'
        )
    )
    manual_controls_widget.add(manual_controls_header)

    # Button container for centering
    button_container = toga.Box(style=Pack(
        direction=COLUMN,
        align_items=CENTER,  # Center the buttons
        background_color='#F0F0F0',
        width=340
    ))

    # Deliver Glucagon Button
    glucagon_button = toga.Button(
        'Deliver Glucagon Dose',
        on_press=lambda widget: asyncio.create_task(deliver_glucagon(app)),
        style=Pack(
            background_color='#8B0000',
            color='white',
            margin=5,
            width=240,
            font_size=16
        )
    )
    # Initially disable the button until pump is connected
    glucagon_button.enabled = False
    button_container.add(glucagon_button)

    # Glucagon delivery status label
    glucagon_delivery_status = toga.Label(
        '',  # Initially empty
        style=Pack(
            font_size=14,
            text_align=CENTER,
            background_color='#F0F0F0',
            width=240
        )
    )
    button_container.add(glucagon_delivery_status)

    # Emergency Contact Button - Updated to use async function
    emergency_button = toga.Button(
        'Notify Emergency Contact',
        on_press=lambda widget: asyncio.create_task(send_emergency_sms(app)),
        style=Pack(
            background_color='#8B0000',
            color='white',
            margin=5,
            width=240,
            font_size=16
        )
    )
    button_container.add(emergency_button)
    manual_controls_widget.add(button_container)
    main_content.add(manual_controls_widget)

    # Small spacer
    main_content.add(toga.Box(style=Pack(height=5, background_color='#F0F0F0')))

    # WIDGET 3: Hourly Glucose Summary
    summary_widget = toga.Box(style=Pack(
        direction=COLUMN,
        margin=5,
        background_color='#F0F0F0',
        width=340,
        align_items='start'
    ))

    # Widget Header - left-aligned with very minimal spacing
    summary_header = toga.Label(
        'Hourly Glucose Summary',
        style=Pack(
            font_size=18,
            font_weight='bold',
            text_align=LEFT,
            margin_bottom=0,  # Almost no spacing
            background_color='#F0F0F0'
        )
    )
    summary_widget.add(summary_header)

    # Summary content container - left-aligned
    summary_content = toga.Box(style=Pack(
        direction=COLUMN,
        margin=0,  # No margin
        background_color='#F0F0F0',
        align_items='start',
        width=340
    ))

    # Average Glucose Row - left-aligned with header
    avg_row = toga.Box(style=Pack(
        direction=ROW,
        margin=2,
        background_color='#F0F0F0',
        width=320,
        align_items='start'
    ))

    avg_title = toga.Label(
        'Average Glucose:',
        style=Pack(
            font_size=14,
            font_weight='bold',
            text_align=LEFT,
            background_color='#F0F0F0',
            width=160
        )
    )

    avg_value_container = toga.Box(style=Pack(
        direction=ROW,
        background_color='#F0F0F0',
        align_items='start',
        width=160
    ))

    avg_glucose_value_label = toga.Label(
        "",  # Start blank
        style=Pack(
            font_size=16,
            font_weight='bold',
            text_align=LEFT,  # Left-aligned value
            background_color='#F0F0F0',
            width=60
        )
    )

    avg_units = toga.Label(
        "mg/dL",
        style=Pack(
            font_size=14,
            text_align=RIGHT,  # Right-aligned units
            background_color='#F0F0F0',
            width=100
        )
    )

    avg_value_container.add(avg_glucose_value_label)
    avg_value_container.add(avg_units)
    avg_row.add(avg_title)
    avg_row.add(avg_value_container)
    summary_content.add(avg_row)

    # GMI Row - left-aligned with header
    gmi_row = toga.Box(style=Pack(
        direction=ROW,
        margin=2,
        background_color='#F0F0F0',
        width=320,
        align_items='start'
    ))

    gmi_title = toga.Label(
        'Glucose Management Index:',
        style=Pack(
            font_size=14,
            font_weight='bold',
            text_align=LEFT,
            background_color='#F0F0F0',
            width=200
        )
    )

    gmi_value_container = toga.Box(style=Pack(
        direction=ROW,
        background_color='#F0F0F0',
        align_items='start',
        width=120
    ))

    gmi_value_label = toga.Label(
        "",  # Start blank
        style=Pack(
            font_size=16,
            font_weight='bold',
            text_align=LEFT,  # Left-aligned value
            background_color='#F0F0F0',
            width=50  # Increased width to fit the full value
        )
    )

    gmi_units = toga.Label(
        "%",
        style=Pack(
            font_size=14,
            text_align=RIGHT,  # Right-aligned units
            background_color='#F0F0F0',
            width=70  # Adjusted width to account for the larger GMI value
        )
    )

    gmi_value_container.add(gmi_value_label)
    gmi_value_container.add(gmi_units)
    gmi_row.add(gmi_title)
    gmi_row.add(gmi_value_container)
    summary_content.add(gmi_row)

    # Add some extra space at the bottom to ensure all content is visible
    summary_content.add(toga.Box(style=Pack(height=40, background_color='#F0F0F0')))

    summary_widget.add(summary_content)
    main_content.add(summary_widget)

    # Set up the scroll container
    scroll_container.content = main_content
    scroll_container.style.update(background_color='#F0F0F0')
    app.content_box.add(scroll_container)

    # Set up background tasks
    start_update_timer()

    # Use the newer method to create the background task to avoid deprecation warning
    asyncio.create_task(monitor_pump_connection(app))

    return scroll_container