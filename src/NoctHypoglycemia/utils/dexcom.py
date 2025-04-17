"""
Dexcom CGM integration utility for NoctHypoglycemia app.

This module provides functions to connect to the Dexcom Share service,
fetch real-time glucose data, and handle the data for use in the application.
"""

import asyncio
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Callable

try:
    from pydexcom import Dexcom

    PYDEXCOM_AVAILABLE = True
except ImportError:
    PYDEXCOM_AVAILABLE = False


class DexcomManager:
    """Manager class for Dexcom CGM integration."""

    def __init__(self, app=None):
        """Initialize the Dexcom manager.

        Args:
            app: Reference to the main Toga app instance
        """
        self.app = app
        self.dexcom = None
        self.connected = False
        self.last_reading = None
        self.last_readings = []
        self.max_readings = 48  # Store last 4 hours of readings (assuming 5 min intervals)
        self.update_interval = 300  # 5 minutes in seconds
        self.update_thread = None
        self.running = False
        self.callbacks = []

    def connect(self, username: str, password: str, region: str = "us") -> bool:
        """Connect to the Dexcom Share service.

        Args:
            username: Dexcom Share username
            password: Dexcom Share password
            region: Region code - "us" (default), "ous" (outside US), or "jp" (Japan)

        Returns:
            bool: True if connection is successful, False otherwise
        """
        if not PYDEXCOM_AVAILABLE:
            print("Error: pydexcom package is not installed")
            return False

        try:
            self.dexcom = Dexcom(username=username, password=password, region=region)
            self.connected = True
            # Fetch initial reading to verify connection
            reading = self.dexcom.get_current_glucose_reading()
            if reading:
                self.last_reading = reading
                self.last_readings = [reading]
            return True
        except Exception as e:
            print(f"Error connecting to Dexcom: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from the Dexcom service and stop updates."""
        self.stop_updates()
        self.dexcom = None
        self.connected = False

    def get_current_reading(self):
        """Get the most recent glucose reading.

        Returns:
            The most recent glucose reading object or None if not available
        """
        if not self.connected or not self.dexcom:
            return None

        try:
            reading = self.dexcom.get_current_glucose_reading()
            if reading:
                self.last_reading = reading
                self._add_reading(reading)
            return reading
        except Exception as e:
            print(f"Error fetching glucose reading: {e}")
            return self.last_reading

    def get_glucose_history(self, hours: int = 3) -> List:
        """Get glucose reading history.

        Args:
            hours: Number of hours to retrieve (default: 3)

        Returns:
            List of glucose readings
        """
        if not self.connected or not self.dexcom:
            return self.last_readings

        try:
            # Use stored readings if we have enough
            if len(self.last_readings) >= (hours * 12):  # 12 readings per hour (5 min intervals)
                return self.last_readings[-(hours * 12):]

            # Otherwise fetch from Dexcom
            minutes = hours * 60
            readings = self.dexcom.get_glucose_readings(minutes=minutes)
            if readings:
                self.last_readings = readings
            return readings
        except Exception as e:
            print(f"Error fetching glucose history: {e}")
            return self.last_readings

    def start_updates(self):
        """Start automatic background updates of glucose readings."""
        if self.running or not self.connected:
            return

        self.running = True
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()

    def stop_updates(self):
        """Stop automatic background updates."""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=1)
            self.update_thread = None

    def register_callback(self, callback: Callable):
        """Register a callback function to be called when new readings arrive.

        Args:
            callback: Function to call with the new glucose reading
        """
        if callback not in self.callbacks:
            self.callbacks.append(callback)

    def unregister_callback(self, callback: Callable):
        """Unregister a previously registered callback function.

        Args:
            callback: Function to remove from callbacks
        """
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def _add_reading(self, reading):
        """Add a reading to the history list, maintaining max size."""
        if reading not in self.last_readings:
            self.last_readings.append(reading)
            # Trim list if it exceeds max size
            if len(self.last_readings) > self.max_readings:
                self.last_readings = self.last_readings[-self.max_readings:]

    def _update_loop(self):
        """Background thread loop to fetch readings periodically."""
        while self.running:
            try:
                reading = self.get_current_reading()
                if reading:
                    # Notify all registered callbacks
                    for callback in self.callbacks:
                        try:
                            callback(reading)
                        except Exception as e:
                            print(f"Error in callback: {e}")
            except Exception as e:
                print(f"Error in update loop: {e}")

            # Sleep until next update
            for _ in range(self.update_interval):
                if not self.running:
                    break
                time.sleep(1)


class DexcomSimulator:
    """Simulator class for testing without an actual Dexcom connection."""

    def __init__(self, app=None):
        """Initialize the Dexcom simulator.

        Args:
            app: Reference to the main Toga app instance
        """
        self.app = app
        self.connected = False
        self.last_reading = None
        self.last_readings = []
        self.max_readings = 48
        self.update_interval = 300
        self.update_thread = None
        self.running = False
        self.callbacks = []
        self.trend_pattern = [0, 0, 1, 1, 2, 2, 3, 4, 4, 3, 3, 3]  # Pattern of trend values
        self.current_pattern_index = 0

    def connect(self, *args, **kwargs) -> bool:
        """Simulate connecting to Dexcom service.

        Returns:
            bool: Always True for simulator
        """
        self.connected = True
        self._generate_reading()
        return True

    def disconnect(self):
        """Simulate disconnecting from Dexcom service."""
        self.stop_updates()
        self.connected = False

    def get_current_reading(self):
        """Get simulated current glucose reading.

        Returns:
            Simulated glucose reading object
        """
        if not self.connected:
            return None

        return self._generate_reading()

    def get_glucose_history(self, hours: int = 3) -> List:
        """Get simulated glucose reading history.

        Args:
            hours: Number of hours to retrieve

        Returns:
            List of simulated glucose readings
        """
        if not self.connected:
            return []

        # Generate history if we don't have enough readings
        readings_needed = hours * 12  # 12 readings per hour (5 min intervals)
        while len(self.last_readings) < readings_needed:
            self._generate_reading(historical=True)

        return self.last_readings[-readings_needed:]

    def start_updates(self):
        """Start automatic background updates with simulated readings."""
        if self.running:
            return

        self.running = True
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()

    def stop_updates(self):
        """Stop automatic background updates."""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=1)
            self.update_thread = None

    def register_callback(self, callback: Callable):
        """Register a callback function for new readings.

        Args:
            callback: Function to call with new glucose readings
        """
        if callback not in self.callbacks:
            self.callbacks.append(callback)

    def unregister_callback(self, callback: Callable):
        """Unregister a callback function.

        Args:
            callback: Function to remove from callbacks
        """
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def _generate_reading(self, historical=False):
        """Generate a simulated glucose reading.

        Args:
            historical: If True, generate a reading for history

        Returns:
            Simulated glucose reading object
        """

        # Create a simple glucose reading simulation
        class SimulatedReading:
            def __init__(self, value, trend, timestamp=None):
                self.value = value
                self.trend = trend
                self.datetime = timestamp or datetime.now()

                # Map trend values to descriptions
                trend_directions = {
                    0: "DoubleUp",
                    1: "SingleUp",
                    2: "FortyFiveUp",
                    3: "Flat",
                    4: "FortyFiveDown",
                    5: "SingleDown",
                    6: "DoubleDown",
                    7: "NotComputable",
                    8: "RateOutOfRange",
                    9: "None"
                }

                trend_descriptions = {
                    0: "rising quickly",
                    1: "rising",
                    2: "rising slightly",
                    3: "steady",
                    4: "falling slightly",
                    5: "falling",
                    6: "falling quickly",
                    7: "unable to determine trend",
                    8: "trend outside measurable range",
                    9: "not available"
                }

                trend_arrows = {
                    0: "↑↑",
                    1: "↑",
                    2: "↗",
                    3: "→",
                    4: "↘",
                    5: "↓",
                    6: "↓↓",
                    7: "?",
                    8: "?",
                    9: "-"
                }

                self.trend_direction = trend_directions[trend]
                self.trend_description = trend_descriptions[trend]
                self.trend_arrow = trend_arrows[trend]
                self.mmol_l = round(value / 18.0, 1)  # Convert mg/dL to mmol/L

            def __str__(self):
                return str(self.value)

        # Base value around 100 mg/dL with some randomness
        if self.last_reading:
            # Add small random change to previous value
            base_value = self.last_reading.value
            change = (-1 if self.trend_pattern[self.current_pattern_index] > 3 else 1) * (
                        1 + self.trend_pattern[self.current_pattern_index] % 3)
            value = base_value + change + (int(time.time()) % 5) - 2  # Small random fluctuation
        else:
            value = 100 + (int(time.time()) % 20) - 10  # Initial value between 90-110

        # Ensure value stays in reasonable range
        value = max(40, min(400, value))

        # Get trend from pattern
        trend = self.trend_pattern[self.current_pattern_index]
        self.current_pattern_index = (self.current_pattern_index + 1) % len(self.trend_pattern)

        # Create timestamp
        if historical:
            # For historical data, create timestamps going back in time
            timestamp = datetime.now() - timedelta(minutes=len(self.last_readings) * 5)
        else:
            timestamp = datetime.now()

        reading = SimulatedReading(value, trend, timestamp)
        self.last_reading = reading

        if not historical:
            self.last_readings.append(reading)
            # Trim list if it exceeds max size
            if len(self.last_readings) > self.max_readings:
                self.last_readings = self.last_readings[-self.max_readings:]

        return reading

    def _update_loop(self):
        """Background thread loop to generate readings periodically."""
        while self.running:
            try:
                reading = self._generate_reading()
                # Notify all registered callbacks
                for callback in self.callbacks:
                    try:
                        callback(reading)
                    except Exception as e:
                        print(f"Error in callback: {e}")
            except Exception as e:
                print(f"Error in simulator update loop: {e}")

            # Sleep until next update (using shorter intervals for testing)
            update_time = 30 if self.update_interval > 60 else self.update_interval
            for _ in range(update_time):
                if not self.running:
                    break
                time.sleep(1)


# Create a singleton instance to be used throughout the app
_instance = None


def get_dexcom_manager(app=None, use_simulator=True):
    """Get the singleton instance of the Dexcom manager.

    Args:
        app: Reference to the main app
        use_simulator: Whether to use the simulator instead of real Dexcom

    Returns:
        A DexcomManager or DexcomSimulator instance
    """
    global _instance

    if _instance is None:
        if use_simulator:
            _instance = DexcomSimulator(app)
        else:
            _instance = DexcomManager(app)

    return _instance


# Example usage for app integration:
"""
# In app.py startup() method:
from NoctHypoglycemia.utils.dexcom import get_dexcom_manager

def startup(self):
    # Initialize Dexcom manager (simulator for testing)
    self.dexcom_manager = get_dexcom_manager(app=self, use_simulator=True)
    self.dexcom_manager.connect()
    self.dexcom_manager.start_updates()

    # Register callback to update UI when new readings arrive
    self.dexcom_manager.register_callback(self.on_glucose_updated)

    # ... rest of startup code ...

def on_glucose_updated(self, reading):
    # This will be called when new readings arrive
    print(f"New glucose reading: {reading.value} mg/dL, Trend: {reading.trend_arrow}")
    # Update UI here, typically by dispatching to the main thread
    # since this callback may happen in a background thread
"""