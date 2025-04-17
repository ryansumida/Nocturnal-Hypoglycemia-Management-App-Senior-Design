import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER
import numpy as np
import pandas as pd
import datetime
import threading
import time
import math
import asyncio
from pathlib import Path
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import webbrowser

# Import the Toga Chart widget and LineSeries class.
from toga_chart import Chart
from toga_chart.line import LineSeries

# Import Kalman filter utilities
from ..utils.kalman_filter import multi_horizon_prediction, OPTIMAL_Q, OPTIMAL_R, OPTIMAL_P0
from NoctHypoglycemia.utils.protocols import check_glucose_predictions, hyper_state, severe_hypo_state, mild_hypo_state

# Import the new Dexcom integration modules
from ..tabs.dexcom_dialog import open_dexcom_session_dialog
from ..tabs.dexcom_integration import start_dexcom_session, stop_dexcom_session, dexcom_session
from ..utils.protocols import stop_severe_hypo_protocol, stop_mild_hypo_protocol, stop_hyperglycemia_protocol, \
    control_arduino_motor

# Import Firebase manager
from ..utils.firebase_manager import firebase_manager


# Utility functions to list patient folders and datasets.
def get_patient_list(base_path):
    base = Path(base_path)
    if not base.exists():
        return []
    patients = [d.name for d in base.iterdir() if d.is_dir() and d.name.lower().startswith("patient id")]
    return sorted(patients)


def get_night_datasets(base_path, patient):
    patient_path = Path(base_path) / patient
    if not patient_path.exists():
        return []
    files = [f.name for f in patient_path.iterdir() if f.is_file() and f.suffix.lower() in ['.xlsx', '.csv']]
    return sorted(files)


# Global simulation state to persist across tab switches
class SimulationState:
    def __init__(self):
        self.active = False
        self.thread = None
        self.times = []
        self.glucose = []
        self.full_times = []
        self.full_glucose = []
        self.current_index = 0
        # Basic Kalman filter data
        self.kalman_filtered = []
        # Current prediction data
        self.kalman_prediction_times = []
        self.kalman_predictions = []
        self.last_prediction_time = None
        # Historical prediction data (to show prediction trails)
        self.all_prediction_times = []  # List of all prediction timestamps
        self.all_predictions = []  # List of all prediction values


# Create a global instance to be shared across components
sim_state = SimulationState()

# Colors for threshold lines to match protocol boxes
HYPERGLYCEMIA_COLOR = 'darkorange'
MILD_HYPOGLYCEMIA_COLOR = 'goldenrod'
SEVERE_HYPOGLYCEMIA_COLOR = 'darkblue'
NORMAL_RANGE_COLOR = 'green'
KALMAN_PREDICTION_COLOR = 'green'


class GlucoseHistoryWidget:
    def __init__(self, app):
        self.app = app
        self.loop = asyncio.get_event_loop()
        self.container = toga.Box(style=Pack(
            direction=COLUMN,
            margin=10,
            background_color='#F0F0F0',
            width=340  # Reduced from 373 to 340
        ))

        # Initialize Firebase
        firebase_manager.initialize()

        # Header with title.
        self.header = toga.Box(style=Pack(
            direction=ROW,
            margin=(0, 0, 10, 0),
            background_color='#F0F0F0',
            align_items='start'  # Change from CENTER to 'start'
        ))
        self.title = toga.Label(
            'Glucose History',
            style=Pack(font_size=18, font_weight='bold', text_align='left', background_color='#F0F0F0')
            # Change from text_align=CENTER to 'left'
        )
        self.header.add(self.title)
        self.container.add(self.header)

        # Time range buttons.
        self.time_buttons = toga.Box(style=Pack(
            direction=ROW,
            margin=(0, 0, 10, 0),
            background_color='#F0F0F0',
            align_items=CENTER
        ))
        button_texts = ["4 hours", "8 hours", "12 hours", "16 hours"]
        self.time_range_buttons = []
        for text in button_texts:
            hours = int(text.split()[0])
            button = toga.Button(
                text,
                on_press=lambda widget, h=hours: self.update_time_range(h),
                style=Pack(margin=5, background_color='#003366', color='white', width=70)  # Reduced width from 80 to 70
            )
            self.time_range_buttons.append(button)
            self.time_buttons.add(button)
        self.container.add(self.time_buttons)

        # Simulation controls box with dropdowns.
        sim_box = toga.Box(style=Pack(
            direction=COLUMN,
            margin=10,
            background_color='#F0F0F0',
            align_items=CENTER
        ))

        # Create the Dexcom button first
        self.dexcom_button = toga.Button(
            'Start CGM Session',
            on_press=self.start_dexcom_session,
            style=Pack(margin=10, background_color='#003366', color='white', width=200)
        )
        sim_box.add(self.dexcom_button)

        # Create the simulate button
        self.simulate_button = toga.Button(
            'Simulate CGM Data Feed',
            on_press=self.start_simulation,
            style=Pack(margin=10, background_color='#FF6600', color='white', width=200)
        )
        sim_box.add(self.simulate_button)

        self.base_data_path = r"C:\Users\rsumi\Downloads\ExampleCGMData"
        patient_list = get_patient_list(self.base_data_path)
        self.patient_selector = toga.Selection(
            items=patient_list,
            value=patient_list[0] if patient_list else None,
            style=Pack(width=200)
        )
        sim_box.add(toga.Label("Select Patient:", style=Pack(margin_top=5)))
        sim_box.add(self.patient_selector)
        night_list = get_night_datasets(self.base_data_path,
                                        self.patient_selector.value) if self.patient_selector.value else []
        self.night_selector = toga.Selection(
            items=night_list,
            value=night_list[0] if night_list else None,
            style=Pack(width=200)
        )
        sim_box.add(toga.Label("Select Night Dataset:", style=Pack(margin_top=5)))
        sim_box.add(self.night_selector)
        self.container.add(sim_box)

        # Create the Toga Chart widget.
        self.chart = Chart("")  # Remove the title as requested
        self.chart.x_label = "Time"
        self.chart.y_label = "Glucose (mg/dL)"

        # Create LineSeries instances for glucose and prediction
        self.glucose_series = LineSeries("Glucose Data", data=[])
        self.prediction_series = LineSeries("Kalman Filter Prediction", data=[])

        # Current time range in hours
        self.current_time_range = 4

        # Set up a timer to redraw the chart periodically when the simulation is running
        self.update_timer = None
        self.setup_update_timer()

        # IMPORTANT: Define the draw handler correctly - needs to accept widget and figure params
        def draw_handler(widget, figure, **kwargs):
            try:
                # Create figure with proper spacing
                figure.subplots_adjust(left=0.15, right=0.95, top=0.9, bottom=0.2)

                # Create the main axis with strict clipping enabled
                ax = figure.add_subplot(111)

                # Force clipping to axis boundary
                ax.set_clip_box(ax.bbox)
                ax.set_clip_on(True)

                # Create a box around the plot area to enforce boundaries
                box = Rectangle(
                    (0, 0), 1, 1,
                    transform=ax.transAxes,
                    fill=False,
                    edgecolor='black',
                    linewidth=1
                )
                ax.add_patch(box)

                # Get the current thresholds from app settings
                try:
                    hyperglycemia_threshold = int(self.app.settings.get('hyperglycemia_threshold', 180))
                    mild_hypoglycemia_threshold = int(self.app.settings.get('hypoglycemia_threshold', 70))
                    severe_hypoglycemia_threshold = int(self.app.settings.get('severe_hypoglycemia_threshold', 54))
                    print(
                        f"Using thresholds: Hyper={hyperglycemia_threshold}, Mild Hypo={mild_hypoglycemia_threshold}, Severe Hypo={severe_hypoglycemia_threshold}")
                except (ValueError, TypeError) as e:
                    print(f"Error parsing threshold values: {e}")
                    # Use defaults if settings are not valid numbers
                    hyperglycemia_threshold = 180
                    mild_hypoglycemia_threshold = 70
                    severe_hypoglycemia_threshold = 54

                # Update the data series from the simulation state
                if sim_state.times and len(sim_state.times) > 0:
                    # Get current time for reference
                    current_time = sim_state.times[-1] if sim_state.times else datetime.datetime.now()

                    # Set time range with no buffer
                    start_time = current_time - datetime.timedelta(hours=self.current_time_range)

                    # Calculate end time to include predictions (add 20 minutes)
                    prediction_buffer = datetime.timedelta(minutes=20)
                    end_time = current_time + prediction_buffer

                    # Filter visible data points
                    visible_times = []
                    visible_glucose = []
                    visible_kalman = []

                    for i, t in enumerate(sim_state.times):
                        if start_time <= t <= end_time:
                            visible_times.append(t)
                            visible_glucose.append(sim_state.glucose[i])

                            # Add filtered values if available
                            if i < len(sim_state.kalman_filtered):
                                visible_kalman.append(sim_state.kalman_filtered[i])

                    # Plot glucose data
                    if visible_times and visible_glucose:
                        glucose_line = ax.plot(visible_times, visible_glucose, 'b.-', label="Glucose Data", alpha=0.7)[
                            0]
                        glucose_line.set_clip_on(True)
                        glucose_line.set_clip_path(box)

                    # Plot Kalman filtered data
                    if visible_times and visible_kalman and len(visible_times) == len(visible_kalman):
                        kalman_line = ax.plot(visible_times, visible_kalman, color='lightgreen', linestyle='-',
                                              label="Kalman Filter", alpha=0.7)[0]
                        kalman_line.set_clip_on(True)
                        kalman_line.set_clip_path(box)

                    # Plot current prediction line
                    if (isinstance(sim_state.kalman_prediction_times, list) and len(
                            sim_state.kalman_prediction_times) > 0 and
                            isinstance(sim_state.kalman_predictions, np.ndarray) and len(
                                sim_state.kalman_predictions) > 0):
                        pred_times = [t for t in sim_state.kalman_prediction_times if start_time <= t <= end_time]
                        pred_values = [sim_state.kalman_predictions[i] for i in range(len(sim_state.kalman_predictions))
                                       if i < len(sim_state.kalman_prediction_times) and
                                       start_time <= sim_state.kalman_prediction_times[i] <= end_time]

                        if pred_times and pred_values and len(pred_times) == len(pred_values):
                            # Add line connecting the most recent real data point to the first prediction
                            if sim_state.times and len(sim_state.times) > 0 and len(pred_times) > 0:
                                # Connect line from latest glucose reading to first prediction
                                connection_x = [sim_state.times[-1], pred_times[0]]
                                connection_y = [sim_state.glucose[-1], pred_values[0]]

                                connection_line = ax.plot(connection_x, connection_y,
                                                          color=KALMAN_PREDICTION_COLOR, linestyle='-', linewidth=2,
                                                          alpha=1.0)[0]
                                connection_line.set_clip_on(True)
                                connection_line.set_clip_path(box)

                            # Plot the current prediction line
                            prediction_line = ax.plot(pred_times, pred_values,
                                                      color=KALMAN_PREDICTION_COLOR, linestyle='-', linewidth=2,
                                                      label="Kalman Prediction", alpha=1.0)[0]
                            prediction_line.set_clip_on(True)
                            prediction_line.set_clip_path(box)

                    # Plot historical predictions (prediction trail)
                    if hasattr(sim_state, 'all_prediction_times') and hasattr(sim_state, 'all_predictions'):
                        if sim_state.all_prediction_times and sim_state.all_predictions:
                            # Filter visible historical predictions
                            hist_times = []
                            hist_values = []

                            for i, t in enumerate(sim_state.all_prediction_times):
                                if i < len(sim_state.all_predictions) and start_time <= t <= end_time:
                                    hist_times.append(t)
                                    hist_values.append(sim_state.all_predictions[i])

                            if hist_times and hist_values:
                                # Plot historical predictions as a lighter green line
                                history_line = ax.plot(hist_times, hist_values,
                                                       color=KALMAN_PREDICTION_COLOR, linestyle='-',
                                                       linewidth=1.5, alpha=0.5)[0]
                                history_line.set_clip_on(True)
                                history_line.set_clip_path(box)

                    # Set x-axis limits to include prediction time
                    ax.set_xlim(start_time, end_time)

                    # Calculate appropriate y-axis limits
                    all_glucose = visible_glucose.copy()

                    # Include prediction values in y-axis calculation
                    if 'pred_values' in locals() and pred_values:
                        all_glucose.extend(pred_values)

                    # Include historical predictions in y-axis calculation
                    if 'hist_values' in locals() and hist_values:
                        all_glucose.extend(hist_values)

                    if all_glucose:
                        min_val = max(0, min(all_glucose) - 20)  # Don't go below 0
                        max_val = max(all_glucose) + 20

                        # Make sure thresholds are visible
                        min_val = min(min_val, severe_hypoglycemia_threshold - 10)
                        max_val = max(max_val, hyperglycemia_threshold + 10)

                        ax.set_ylim(min_val, max_val)

                    # Format time axis with shorter format to prevent overlap
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

                    # Rotate labels for better readability
                    for label in ax.get_xticklabels():
                        label.set_rotation(45)
                        label.set_ha('right')

                    # Add grid lines for better readability
                    ax.grid(True, linestyle='--', alpha=0.7)

                    # Get current axes limits
                    ymin, ymax = ax.get_ylim()
                    xmin, xmax = ax.get_xlim()

                    # Add horizontal lines for the thresholds with improved visibility
                    # Hyperglycemia threshold (orange)
                    hyperglycemia_line = ax.axhline(
                        y=hyperglycemia_threshold,
                        color=HYPERGLYCEMIA_COLOR,
                        linestyle='--',
                        linewidth=2.0,
                        alpha=1.0,
                        zorder=10  # Higher zorder means drawn on top
                    )

                    # Mild hypoglycemia threshold (goldenrod)
                    mild_hypo_line = ax.axhline(
                        y=mild_hypoglycemia_threshold,
                        color=MILD_HYPOGLYCEMIA_COLOR,
                        linestyle='--',
                        linewidth=2.0,
                        alpha=1.0,
                        zorder=10
                    )

                    # Severe hypoglycemia threshold (darkblue)
                    severe_hypo_line = ax.axhline(
                        y=severe_hypoglycemia_threshold,
                        color=SEVERE_HYPOGLYCEMIA_COLOR,
                        linestyle='--',
                        linewidth=2.0,
                        alpha=1.0,
                        zorder=10
                    )

                    # Add normal range rectangle
                    if ymin <= hyperglycemia_threshold and ymax >= mild_hypoglycemia_threshold:
                        # Clip the range values to the plot limits
                        range_ymin = max(mild_hypoglycemia_threshold, ymin)
                        range_ymax = min(hyperglycemia_threshold, ymax)

                        # Create a rectangle patch bounded by the plot limits
                        rect_height = range_ymax - range_ymin
                        rect = Rectangle(
                            (mdates.date2num(xmin), range_ymin),
                            mdates.date2num(xmax) - mdates.date2num(xmin),
                            rect_height,
                            color=NORMAL_RANGE_COLOR,
                            alpha=0.1
                        )
                        rect.set_clip_on(True)
                        rect.set_clip_box(ax.bbox)
                        ax.add_patch(rect)

                # Add legend with improved positioning
                handles, labels = ax.get_legend_handles_labels()
                if handles:
                    ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.15),
                              ncol=3, frameon=False, fontsize='small')

                # Set all spines to be visible
                for spine in ax.spines.values():
                    spine.set_visible(True)
                    spine.set_linewidth(1.0)

            except Exception as e:
                print(f"Error in draw_handler: {e}")
                import traceback
                traceback.print_exc()

        # Set the on_draw handler - this is the key part!
        self.chart.on_draw = draw_handler

        # Set fixed dimensions on the chart widget with more height for better layout
        self.chart.style = Pack(width=340, height=350)  # Reduced from 373 to 340
        self.container.add(self.chart)

        # Add alerts section after the chart
        self.create_alerts_section()

        # Start checking for alerts to show in the section
        self.start_alerts_monitor()

    def create_alerts_section(self):
        """Create the enhanced alerts section that appears under the chart."""
        # Create the alerts box
        self.alerts_box = toga.Box(style=Pack(
            direction=COLUMN,
            margin=(5, 0, 10, 0),
            background_color='#F0F0F0',
            width=340
        ))

        # Add a header for the alerts section
        alerts_header = toga.Box(style=Pack(
            direction=ROW,
            margin=(0, 0, 5, 0),
            background_color='#F0F0F0',
            align_items='start'
        ))

        alerts_title = toga.Label(
            'Alerts',
            style=Pack(font_size=16, font_weight='bold', text_align='left', background_color='#F0F0F0')
        )
        alerts_header.add(alerts_title)
        self.alerts_box.add(alerts_header)

        # Create alert content container (white box) - increased height for more content
        self.alert_content = toga.Box(style=Pack(
            direction=COLUMN,
            padding=10,
            background_color='white',
            width=340,
            height=120,  # Increased from 80 to 120 to accommodate more text
            align_items=CENTER
        ))

        # Initially empty alert message
        self.alert_message = toga.Label(
            '',  # Initially empty
            style=Pack(
                font_size=16,
                font_weight='bold',
                text_align=CENTER,
                color='black'
            )
        )
        self.alert_content.add(self.alert_message)

        # Add treatment instructions label (initially empty)
        self.treatment_label = toga.Label(
            '',  # Initially empty
            style=Pack(
                font_size=14,
                text_align=CENTER,
                color='black',
                padding_top=5
            )
        )
        self.alert_content.add(self.treatment_label)

        # Button container for horizontal arrangement
        self.button_container = toga.Box(style=Pack(
            direction=ROW,
            padding_top=10,
            align_items=CENTER
        ))

        # Add dismiss button
        self.dismiss_button = toga.Button(
            'Dismiss',
            on_press=self.clear_alert,
            style=Pack(
                background_color='#666666',
                color='white',
                padding=5,
                margin=(0, 5),
                width=100
            )
        )
        self.button_container.add(self.dismiss_button)

        # Create stop motor button - not added yet
        self.stop_motor_button = toga.Button(
            'Stop Motor',
            on_press=self.stop_arduino_motor,
            style=Pack(
                background_color='#CC0000',
                color='white',
                padding=5,
                margin=(0, 5),
                width=100
            )
        )

        # Add button container to alert content
        self.alert_content.add(self.button_container)

        # Add content container to alerts box
        self.alerts_box.add(self.alert_content)

        # Add alerts box to the main container
        self.container.add(self.alerts_box)

    def set_alert(self, alert_type, value=None):
        """Set an alert in the alerts section with enhanced features."""
        # Save the current scroll position
        scroll_container = self._find_scroll_container()
        scroll_position = self._get_scroll_position(scroll_container)

        # Reset button container - remove all previous buttons
        self.button_container.remove(*self.button_container.children)
        self.button_container.add(self.dismiss_button)

        # Clear treatment instructions
        self.treatment_label.text = ''

        # Determine alert styling based on type
        if alert_type == "hyperglycemia":
            self.alert_message.text = "HYPERGLYCEMIA"
            self.alert_message.style.color = 'white'
            self.alert_content.style.background_color = HYPERGLYCEMIA_COLOR
            self.dismiss_button.style.background_color = '#666666'

            # Add value to alert if provided
            if value is not None:
                predicted_value = int(value)
                self.alert_message.text += f"\nPredicted: {predicted_value} mg/dL"

        elif alert_type == "mild_hypoglycemia":
            self.alert_message.text = "MILD HYPOGLYCEMIA"
            self.alert_message.style.color = 'white'
            self.alert_content.style.background_color = MILD_HYPOGLYCEMIA_COLOR
            self.dismiss_button.style.background_color = '#666666'

            # Add value to alert if provided
            if value is not None:
                predicted_value = int(value)
                self.alert_message.text += f"\nPredicted: {predicted_value} mg/dL"

            # Add treatment instructions
            self.treatment_label.text = "Eat 15g of carbohydrates and wait 15 minutes"
            self.treatment_label.style.color = 'white'

        elif alert_type == "severe_hypoglycemia":
            self.alert_message.text = "SEVERE HYPOGLYCEMIA"
            self.alert_message.style.color = 'white'
            self.alert_content.style.background_color = SEVERE_HYPOGLYCEMIA_COLOR
            self.dismiss_button.style.background_color = '#666666'

            # Add value to alert if provided
            if value is not None:
                predicted_value = int(value)
                self.alert_message.text += f"\nPredicted: {predicted_value} mg/dL"

            # Add treatment instructions
            self.treatment_label.text = "EMERGENCY TREATMENT REQUIRED"
            self.treatment_label.style.color = 'white'

            # Check if Arduino connection exists and add stop motor button if it does
            if hasattr(self.app, 'arduino_connection') and self.app.arduino_connection:
                self.button_container.add(self.stop_motor_button)

        else:
            # Clear the alert if type is unknown
            self.clear_alert(None)
            return

        # Make sure the dismiss button is enabled
        self.dismiss_button.enabled = True

        print(f"Alert set: {alert_type}")

        # Restore scroll position
        self._restore_scroll(scroll_container, scroll_position)

    def clear_alert(self, widget):
        """Clear the currently displayed alert and stop the protocol while preserving scroll position."""
        # Save scroll position before making any changes
        scroll_container = self._find_scroll_container()
        scroll_position = self._get_scroll_position(scroll_container)

        # Clear the alert display
        self.alert_message.text = ''
        self.alert_message.style.color = 'black'
        self.alert_content.style.background_color = 'white'
        self.treatment_label.text = ''

        # Reset button container - remove all buttons except dismiss
        for child in list(self.button_container.children):
            if child != self.dismiss_button:
                self.button_container.remove(child)

        # Stop the active protocol (including any alarms)
        if severe_hypo_state.active:
            stop_severe_hypo_protocol(self.app)  # Pass app to stop Arduino motor
        elif mild_hypo_state.active:
            stop_mild_hypo_protocol()
        elif hyper_state.active:
            stop_hyperglycemia_protocol()

        print("Alert dismissed and protocol stopped")

        # Restore scroll position after UI changes
        self._restore_scroll(scroll_container, scroll_position)

    def stop_arduino_motor(self, widget):
        """Stop the Arduino motor without dismissing the alert."""
        if hasattr(self.app, 'arduino_connection') and self.app.arduino_connection:
            # Call function to stop motor
            from ..utils.protocols import control_arduino_motor
            control_arduino_motor(self.app, start=False)

            # Update button to show it's been pressed
            self.stop_motor_button.style.background_color = '#777777'
            self.stop_motor_button.enabled = False
            self.stop_motor_button.text = "Motor Stopped"

            print("Arduino motor stopped manually")
        else:
            print("No Arduino connection available")

    def start_alerts_monitor(self):
        """Start a background task to check for alerts."""

        async def check_alerts():
            # Track the previous state to avoid unnecessary updates
            previous_state = {
                "severe": False,
                "mild": False,
                "hyper": False
            }

            while True:
                # Check for active protocols and update alerts accordingly
                try:
                    # Only update if there's been a state change
                    if severe_hypo_state.active != previous_state["severe"]:
                        previous_state["severe"] = severe_hypo_state.active
                        if severe_hypo_state.active:
                            # Show severe hypoglycemia alert with the predicted value
                            predicted_value = severe_hypo_state.predicted_value
                            self.app.loop.call_soon_threadsafe(
                                lambda: self.set_alert("severe_hypoglycemia", predicted_value)
                            )
                    elif mild_hypo_state.active != previous_state["mild"]:
                        previous_state["mild"] = mild_hypo_state.active
                        if mild_hypo_state.active:
                            # Show mild hypoglycemia alert with the predicted value
                            predicted_value = mild_hypo_state.predicted_value
                            self.app.loop.call_soon_threadsafe(
                                lambda: self.set_alert("mild_hypoglycemia", predicted_value)
                            )
                    elif hyper_state.active != previous_state["hyper"]:
                        previous_state["hyper"] = hyper_state.active
                        if hyper_state.active:
                            # Show hyperglycemia alert with the predicted value
                            predicted_value = hyper_state.predicted_value
                            self.app.loop.call_soon_threadsafe(
                                lambda: self.set_alert("hyperglycemia", predicted_value)
                            )
                except Exception as e:
                    print(f"Error in alerts monitor: {e}")

                # Check every second
                await asyncio.sleep(1)

        # Start the alert monitoring task
        asyncio.ensure_future(check_alerts())

    def _find_scroll_container(self):
        """Find the scroll container in the widget hierarchy."""
        # Start by checking the main window's immediate children
        for widget in self.app.main_window.content.children:
            if isinstance(widget, toga.ScrollContainer):
                return widget

        # If not found, try searching more deeply in the window's widget tree
        def find_scroll(widget):
            if isinstance(widget, toga.ScrollContainer):
                return widget
            if hasattr(widget, 'children'):
                for child in widget.children:
                    result = find_scroll(child)
                    if result:
                        return result
            return None

        return find_scroll(self.app.main_window.content)

    def _get_scroll_position(self, scroll_container):
        """Get the current scroll position from a scroll container."""
        if not scroll_container:
            return None

        try:
            # Different Toga backends might have different ways to access scroll position
            if hasattr(scroll_container, 'vertical_position'):
                return scroll_container.vertical_position
            elif hasattr(scroll_container, 'vertical'):
                return scroll_container.vertical
            # For BeeWare 0.3.0+, try to access the implementation's scroll position
            elif hasattr(scroll_container, '_impl') and hasattr(scroll_container._impl, 'get_vertical_position'):
                return scroll_container._impl.get_vertical_position()
        except Exception as e:
            print(f"Error getting scroll position: {e}")

        return None

    def _restore_scroll(self, scroll_container, position):
        """Restore a saved scroll position with retry mechanism."""
        if not scroll_container or position is None:
            return

        # Helper function to apply scroll position
        def apply_scroll():
            try:
                # Try different methods depending on what the scroll container supports
                if hasattr(scroll_container, 'vertical_position'):
                    scroll_container.vertical_position = position
                elif hasattr(scroll_container, 'vertical'):
                    scroll_container.vertical = position
                # For BeeWare 0.3.0+
                elif hasattr(scroll_container, '_impl') and hasattr(scroll_container._impl, 'set_vertical_position'):
                    scroll_container._impl.set_vertical_position(position)
                print(f"Restored scroll position to {position}")
            except Exception as e:
                print(f"Error restoring scroll position: {e}")

        # Schedule multiple restoration attempts with increasing delays
        # This helps ensure it works even if the UI is still updating
        self.app.loop.call_later(0.05, apply_scroll)  # Try soon
        self.app.loop.call_later(0.1, apply_scroll)  # Try again a bit later
        self.app.loop.call_later(0.25, apply_scroll)  # Final attempt

    def setup_update_timer(self):
        """Set up a timer to update the chart for both simulation and Dexcom data."""

        async def update_chart():
            last_data_length = 0  # Track the number of data points

            while True:
                # Check if there's any active data source
                if sim_state.active:
                    # Always update for Dexcom sessions regardless of data length
                    if dexcom_session.active:
                        try:
                            self.chart.redraw()

                            # Log current data for debugging
                            current_data_length = len(sim_state.times)
                            if current_data_length != last_data_length:
                                last_data_length = current_data_length
                                print(f"Chart updated with data point count: {current_data_length}")
                                if current_data_length > 0:
                                    latest_time = sim_state.times[-1]
                                    latest_glucose = sim_state.glucose[-1]
                                    print(f"Latest reading: {latest_glucose} mg/dL at {latest_time}")
                        except Exception as e:
                            print(f"Error in update_chart: {e}")
                    # For simulation, only update when new data is available
                    elif len(sim_state.times) > last_data_length:
                        try:
                            current_data_length = len(sim_state.times)
                            last_data_length = current_data_length
                            self.chart.redraw()
                            print(f"Chart updated with data point count: {current_data_length}")
                        except Exception as e:
                            print(f"Error in update_chart: {e}")

                # Check more frequently during Dexcom sessions
                check_interval = 5 if dexcom_session.active else 10
                await asyncio.sleep(check_interval)

        # Start the update timer
        self.update_timer = asyncio.ensure_future(update_chart())

    def update_time_range(self, hours):
        """Update the time range displayed on the chart."""
        self.current_time_range = hours
        print(f"Updating time range to {hours} hours")
        self.chart.redraw()

    def start_dexcom_session(self, widget):
        """Open dialog to start a Dexcom CGM session."""
        global sim_state, dexcom_session

        # If simulation is running, stop it
        if sim_state.active:
            sim_state.active = False
            if sim_state.thread and sim_state.thread.is_alive():
                sim_state.thread.join(timeout=0.5)
            self.simulate_button.label = 'Simulate CGM Data Feed'

        # If Dexcom session is active, stop it
        if dexcom_session.active:
            stop_dexcom_session(sim_state)
            self.dexcom_button.label = 'Start CGM Session'
            return

        # Open dialog to get Dexcom credentials
        open_dexcom_session_dialog(self.app, self.on_dexcom_credentials)

    def on_dexcom_credentials(self, username, password):
        """Handle Dexcom credentials submission."""
        global sim_state

        # Start the Dexcom session
        success = start_dexcom_session(self.app, sim_state, username, password)

        if success:
            # Start a new Firebase session for Dexcom data
            firebase_manager.start_new_session("Dexcom")

            self.dexcom_button.label = 'Stop CGM Session'
            self.simulate_button.label = 'Simulate CGM Data Feed'
        else:
            self.app.main_window.info_dialog(
                'Connection Failed',
                'Failed to connect to Dexcom. Please check your credentials and try again.'
            )

    def start_simulation(self, widget):
        """Start or stop the CGM simulation."""
        global sim_state, dexcom_session

        if sim_state.active:
            # Stop the simulation
            sim_state.active = False
            if sim_state.thread and sim_state.thread.is_alive():
                sim_state.thread.join(timeout=0.5)  # Give it time to cleanly exit
            self.simulate_button.label = 'Simulate CGM Data Feed'
            return

        # If Dexcom session is active, stop it first
        if dexcom_session.active:
            stop_dexcom_session(sim_state)
            self.dexcom_button.label = 'Start CGM Session'

        # Start a new simulation
        selected_patient = self.patient_selector.value
        selected_night = self.night_selector.value
        if not selected_patient or not selected_night:
            return

        # Initialize Firebase if needed (should already be initialized in __init__)
        if not firebase_manager.db:
            firebase_manager.initialize()

        # Start a new Firebase session
        firebase_manager.start_new_session("Simulation")

        file_path = Path(self.base_data_path) / selected_patient / selected_night
        try:
            if file_path.suffix.lower() == '.csv':
                data = pd.read_csv(file_path)
            else:
                data = pd.read_excel(file_path)

            # Assume glucose data is in the second column and time in the third
            sim_state.full_glucose = data.iloc[:, 1].values
            time_str = data.iloc[:, 2].values

            try:
                # Sample time string
                sample = time_str[0]
                print(f"Sample time format: {sample}")

                # Add today's date to create full datetime objects
                today = datetime.datetime.now().date()
                time_with_date = [f"{today} {t}" for t in time_str]

                # Use automatic format detection
                print("Using automatic format detection for times...")
                sim_state.full_times = pd.to_datetime(time_with_date).tolist()
                print(f"Successfully loaded {len(sim_state.full_times)} data points")

            except Exception as e:
                print(f"Error parsing time: {e}")
                return
        except Exception as e:
            print(f"Error loading data: {e}")
            return

        # Reset simulation state
        sim_state.times = []
        sim_state.glucose = []
        sim_state.kalman_filtered = []
        sim_state.kalman_prediction_times = []
        sim_state.kalman_predictions = []
        sim_state.all_prediction_times = []  # Reset historical predictions
        sim_state.all_predictions = []  # Reset historical predictions
        sim_state.current_index = 0
        sim_state.active = True

        # Find and reset the data table widget if it exists
        # Look for DataTableWidget instances in the app
        for tab in self.app.main_window.content.children:
            if hasattr(tab, 'content'):
                for widget in tab.content.children:
                    if isinstance(widget, DataTableWidget):
                        # Reset the table
                        widget.data_table.update_data([])
                        widget.last_data_length = 0
                        widget.last_update_time = None
                        print("Data table cleared for new simulation")
                    # Also check inside BoxContainers
                    elif hasattr(widget, 'children'):
                        for child in widget.children:
                            if isinstance(child, DataTableWidget):
                                child.data_table.update_data([])
                                child.last_data_length = 0
                                child.last_update_time = None
                                print("Data table cleared for new simulation")

        # Start simulation thread if not already running
        if not sim_state.thread or not sim_state.thread.is_alive():
            sim_state.thread = threading.Thread(target=self.run_simulation, daemon=True)
            sim_state.thread.start()

        # Update button label
        self.simulate_button.label = 'Stop Simulation'

    def run_simulation(self):
        """Run the CGM simulation in a background thread with enhanced Kalman filtering."""
        global sim_state

        # Reset hyperglycemia protocol initial check flag at the start of a new simulation
        hyper_state.initial_check_complete = False

        # Sample interval in minutes (typical for CGM data)
        interval_minutes = 5

        # Number of steps to predict ahead (from the updated Kalman filter)
        predict_steps = 1  # 5 minutes ahead (1 x 5min) - keeping as requested

        while sim_state.active and sim_state.current_index < len(sim_state.full_glucose):
            # Get current data point
            current_time = sim_state.full_times[sim_state.current_index]
            current_glucose = sim_state.full_glucose[sim_state.current_index]

            # Add to simulation state
            sim_state.times.append(current_time)
            sim_state.glucose.append(current_glucose)

            # Apply Kalman filter and get predictions
            glucose_array = np.array(sim_state.glucose)
            filtered_values, future_predictions, future_minutes = multi_horizon_prediction(
                glucose_array,
                predict_steps=predict_steps,
                interval_minutes=interval_minutes
            )

            # Update kalman filtered data
            sim_state.kalman_filtered = filtered_values

            # Create future prediction times - using regular Python integers, not numpy.int64
            prediction_times = []
            for mins in future_minutes:
                # Convert numpy.int64 to regular Python int if needed
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

            # Determine glucose state based on thresholds
            try:
                hyperglycemia_threshold = int(self.app.settings.get('hyperglycemia_threshold', 180))
                mild_hypoglycemia_threshold = int(self.app.settings.get('hypoglycemia_threshold', 70))
                severe_hypoglycemia_threshold = int(self.app.settings.get('severe_hypoglycemia_threshold', 54))
            except (ValueError, TypeError) as e:
                print(f"Error parsing threshold values: {e}")
                # Use defaults if settings are not valid numbers
                hyperglycemia_threshold = 180
                mild_hypoglycemia_threshold = 70
                severe_hypoglycemia_threshold = 54

            # Determine glucose state
            if current_glucose <= severe_hypoglycemia_threshold:
                state = "Severe Hypoglycemia"
            elif current_glucose <= mild_hypoglycemia_threshold:
                state = "Mild Hypoglycemia"
            elif current_glucose >= hyperglycemia_threshold:
                state = "Hyperglycemia"
            else:
                state = "Normal"

            # Check if any protocol is active
            protocol_active = severe_hypo_state.active or mild_hypo_state.active or hyper_state.active

            # Save to Firebase
            prediction_value = future_predictions[0] if len(future_predictions) > 0 else None
            firebase_manager.save_reading(
                current_time,
                current_glucose,
                prediction_value,
                state,
                protocol_active
            )

            # Get the username for the notification
            username = "Patient"
            if hasattr(self.app, 'remembered_login') and self.app.remembered_login:
                if 'patient_id' in self.app.remembered_login:
                    username = self.app.remembered_login['patient_id']

            # Check all glucose protocols at once
            try:
                check_glucose_predictions(
                    self.app,
                    prediction_times,
                    future_predictions,
                    current_glucose=current_glucose,
                    username=username
                )

            except Exception as e:
                print(f"Error checking glucose protocols: {e}")
                import traceback
                traceback.print_exc()

            # Move to next data point
            sim_state.current_index += 1

            # Signal that UI updates should happen - force synchronous update
            # to ensure plot and table update together
            print(f"Updating display with data point {sim_state.current_index}")
            self.chart.redraw()  # Update the plot

            # Sleep to simulate data feed
            time.sleep(10)

        # Simulation complete or stopped
        sim_state.active = False


# Custom table implementation with fixed column widths
class CustomDataTable:
    def __init__(self, container, widths, headers):
        """Create a custom table with fixed column widths.

        Args:
            container (toga.Box): Container to place the table in
            widths (list): List of column widths in pixels
            headers (list): List of column header texts
        """
        self.container = container
        self.widths = widths
        self.headers = headers
        self.rows = []

        # Style definitions
        self.header_style = Pack(
            font_weight='bold',
            text_align='left',
            padding=(5, 2)
        )

        self.cell_style = Pack(
            text_align='left',
            padding=(5, 2)
        )

        self.row_style = Pack(
            direction=ROW,
            padding=(2, 0),
            background_color='white'
        )

        self.alt_row_style = Pack(
            direction=ROW,
            padding=(2, 0),
            background_color='#F0F0F0'
        )

        # Create header row
        self._create_header_row()

        # Create scroll container for data rows
        self.data_container = toga.Box(style=Pack(
            direction=COLUMN,
            background_color='white',
            width=sum(widths) + 10  # Add a bit of extra width for padding
        ))

        self.scroll_container = toga.ScrollContainer(
            horizontal=False,
            style=Pack(height=200)
        )
        self.scroll_container.content = self.data_container

        # Add scroll container to main container
        self.container.add(self.scroll_container)

    def _create_header_row(self):
        """Create the header row with fixed widths."""
        header_row = toga.Box(style=Pack(
            direction=ROW,
            background_color='#DDDDDD',
            padding=(5, 2)
        ))

        for i, header in enumerate(self.headers):
            header_box = toga.Box(style=Pack(width=self.widths[i]))
            header_box.add(toga.Label(
                header,
                style=self.header_style
            ))
            header_row.add(header_box)

        self.container.add(header_row)

    def update_data(self, data):
        """Update the table with new data.

        Args:
            data (list): List of rows, where each row is a list of cell values
        """
        # Clear existing rows
        self.data_container.remove(*self.data_container.children)
        self.rows = []

        # Add new rows
        for i, row_data in enumerate(data):
            # Alternate row colors for better readability
            style = self.alt_row_style if i % 2 == 1 else self.row_style
            row = toga.Box(style=style)

            for j, cell_value in enumerate(row_data):
                if j >= len(self.widths):
                    continue  # Skip extra cells

                cell_box = toga.Box(style=Pack(width=self.widths[j]))

                # Customize cell style based on content (optional)
                cell_style = self.cell_style

                # For glucose state column, add color indicators
                if j == 3:  # Glucose State column (index 3)
                    if cell_value == "Severe Hypoglycemia":
                        cell_style = Pack(
                            text_align='left',
                            padding=(5, 2),
                            color=SEVERE_HYPOGLYCEMIA_COLOR,
                            font_weight='bold'
                        )
                    elif cell_value == "Mild Hypoglycemia":
                        cell_style = Pack(
                            text_align='left',
                            padding=(5, 2),
                            color=MILD_HYPOGLYCEMIA_COLOR,
                            font_weight='bold'
                        )
                    elif cell_value == "Hyperglycemia":
                        cell_style = Pack(
                            text_align='left',
                            padding=(5, 2),
                            color=HYPERGLYCEMIA_COLOR,
                            font_weight='bold'
                        )
                    elif cell_value == "Normal":
                        cell_style = Pack(
                            text_align='left',
                            padding=(5, 2),
                            color=NORMAL_RANGE_COLOR,
                            font_weight='bold'
                        )

                cell_box.add(toga.Label(str(cell_value), style=cell_style))
                row.add(cell_box)

            self.data_container.add(row)
            self.rows.append(row)


class DataTableWidget:
    def __init__(self, app):
        self.app = app
        self.container = toga.Box(style=Pack(
            direction=COLUMN,
            margin=10,
            background_color='#F0F0F0',
            width=340
        ))

        # Initialize Firebase
        firebase_manager.initialize()

        # Header with title - aligned to start
        self.header = toga.Box(style=Pack(
            direction=ROW,
            margin=(0, 0, 10, 0),
            background_color='#F0F0F0',
            align_items='start'
        ))
        self.title = toga.Label('Past 24 Hour Data', style=Pack(
            font_size=18,
            font_weight='bold',
            text_align='left',
            background_color='#F0F0F0'
        ))
        self.header.add(self.title)
        self.container.add(self.header)

        # Create table container
        self.table_container = toga.Box(style=Pack(
            direction=COLUMN,
            background_color='white',
            width=340
        ))
        self.container.add(self.table_container)

        # Define column widths and headers
        column_widths = [85, 80, 80, 95]  # Total 340px
        column_headers = ['Time', 'Glucose', 'Prediction', 'Glucose State']

        # Create custom table
        self.data_table = CustomDataTable(
            self.table_container,
            column_widths,
            column_headers
        )

        # Initialize tracking variables for updates
        self.last_data_length = 0
        self.last_update_time = None

        # Add the "Past 10 Days of Glucose Data" button
        self.history_button = toga.Button(
            'Past 10 Days of Glucose Data',
            on_press=self.show_long_history,
            style=Pack(
                margin=10,
                background_color='#003366',
                color='white',
                width=250,
                align_items=CENTER
            )
        )

        # Add a button container for centering
        button_container = toga.Box(style=Pack(
            direction=ROW,
            margin=(10, 0, 0, 0),
            background_color='#F0F0F0',
            align_items=CENTER
        ))
        button_container.add(self.history_button)
        self.container.add(button_container)

        # Start a background task to update the table
        self.start_update_task()

    def determine_glucose_state(self, glucose_value):
        """Determine the glucose state based on thresholds."""
        try:
            hyperglycemia_threshold = int(self.app.settings.get('hyperglycemia_threshold', 180))
            mild_hypoglycemia_threshold = int(self.app.settings.get('hypoglycemia_threshold', 70))
            severe_hypoglycemia_threshold = int(self.app.settings.get('severe_hypoglycemia_threshold', 54))
        except (ValueError, TypeError):
            # Use defaults if settings are not valid numbers
            hyperglycemia_threshold = 180
            mild_hypoglycemia_threshold = 70
            severe_hypoglycemia_threshold = 54

        if glucose_value <= severe_hypoglycemia_threshold:
            return "Severe Hypoglycemia"
        elif glucose_value <= mild_hypoglycemia_threshold:
            return "Mild Hypoglycemia"
        elif glucose_value >= hyperglycemia_threshold:
            return "Hyperglycemia"
        else:
            return "Normal"

    def start_update_task(self):
        """Start a background task to update the table."""

        async def update_table():
            while True:
                await asyncio.sleep(1)  # Update every second
                if sim_state.active and sim_state.times and len(sim_state.times) > 0:
                    self.app.add_background_task(self.update_table_data)
                await asyncio.sleep(1)  # Wait a bit before checking again

        # Start the update task
        asyncio.ensure_future(update_table())

    def update_table_data(self, widget=None):
        """Update the table with current data, synchronized with the plot."""
        try:
            if not sim_state.times or len(sim_state.times) == 0:
                # Only clear if we haven't already cleared
                if hasattr(self, 'last_data_length') and self.last_data_length > 0:
                    self.data_table.update_data([])
                    self.last_data_length = 0
                return

            # Get current number of data points - use simulation's current_index as source of truth
            current_data_count = sim_state.current_index

            # Check if we actually have new data - again based on sim_state.current_index
            if hasattr(self, 'last_data_length') and self.last_data_length == current_data_count:
                # No new data, skip the update
                return

            # Get current time for reference (to filter past 24 hours)
            current_time = sim_state.times[-1]
            one_day_ago = current_time - datetime.timedelta(hours=24)

            # Prepare new table data
            table_data = []

            # Build the data in reverse order (newest first)
            for i in range(len(sim_state.times) - 1, -1, -1):
                time = sim_state.times[i]

                # Skip data older than 24 hours
                if time < one_day_ago:
                    continue

                glucose = sim_state.glucose[i]

                # For predictions, look for this time in the historical predictions
                # Each time a prediction is made, it's saved in all_prediction_times and all_predictions
                prediction = ""

                # Look for this time value in all historical predictions
                if hasattr(sim_state, 'all_prediction_times') and sim_state.all_prediction_times:
                    # Find predictions made for this specific time
                    for j, pred_time in enumerate(sim_state.all_prediction_times):
                        if j < len(sim_state.all_predictions) and pred_time == time:
                            # Found a prediction that was made for this time
                            prediction = f"{int(sim_state.all_predictions[j])}"
                            break

                # Determine glucose state
                state = self.determine_glucose_state(glucose)

                # Format time
                time_str = time.strftime("%I:%M %p")

                # Add to table data
                table_data.append([time_str, f"{int(glucose)}", prediction, state])

            # Update the table with our custom method
            self.data_table.update_data(table_data)

            # Save the current state to check for changes - based on sim_state.current_index
            self.last_data_length = current_data_count
            print(f"Table updated to match plot at data point {current_data_count}")

        except Exception as e:
            print(f"Error updating table: {e}")
            import traceback
            traceback.print_exc()

    def show_long_history(self, widget):
        """Show the long-term glucose history from Firebase."""
        # Make sure Firebase is initialized
        if not firebase_manager.db:
            firebase_manager.initialize()

        # For development: show sessions in console first
        sessions = firebase_manager.get_recent_sessions()

        if sessions:
            # Show info in console for debugging
            print(f"Found {len(sessions)} glucose monitoring sessions")
            for i, session in enumerate(sessions[:3]):  # Show first three for brevity
                start_time = session.get('start_time')
                if start_time:
                    if hasattr(start_time, 'strftime'):
                        start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        start_time_str = str(start_time)
                else:
                    start_time_str = "Unknown time"

                device_type = session.get('device_type', 'Unknown')
                readings = session.get('readings', [])

                print(f"Session {i + 1}: {device_type} at {start_time_str} - {len(readings)} readings")

            # Try to open the web view with the history data
            try:
                # Look for the HTML file in the correct location
                # Updated path to match your environment structure
                web_path = Path(r"C:\Users\rsumi\beeware-tutorial\NoctHypoglycemia\web\glucose_history.html")

                if web_path.exists():
                    web_url = web_path.as_uri()
                    webbrowser.open(web_url)
                    print(f"Opening {web_url}")
                else:
                    # Show dialog if web file doesn't exist
                    self.app.main_window.info_dialog(
                        "Glucose History",
                        f"Found {len(sessions)} sessions in database.\nWeb viewer not found at {web_path}"
                    )
            except Exception as e:
                # Fallback to dialog if web view fails
                print(f"Error opening web view: {e}")
                self.app.main_window.info_dialog(
                    "Glucose History",
                    f"Found {len(sessions)} glucose monitoring sessions in Firebase.\n"
                    f"Web view couldn't be opened: {str(e)}"
                )
        else:
            # No data found
            self.app.main_window.info_dialog(
                "Glucose History",
                "No historical glucose data found. Try running a simulation first."
            )


def create_history_tab(app):
    scroll_container = toga.ScrollContainer(horizontal=False, style=Pack(flex=1))  # Remove horizontal scrollbar
    main_content = toga.Box(style=Pack(
        direction=COLUMN,
        margin=10,
        background_color='#F0F0F0',
        flex=1
    ))
    glucose_history = GlucoseHistoryWidget(app)
    main_content.add(glucose_history.container)
    main_content.add(toga.Box(style=Pack(height=15, background_color='#F0F0F0')))
    data_table = DataTableWidget(app)
    main_content.add(data_table.container)
    scroll_container.content = main_content
    app.content_box.add(scroll_container)
    return scroll_container  # Return the container in case it needs to be referenced later