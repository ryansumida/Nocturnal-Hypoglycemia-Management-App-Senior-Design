import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER, LEFT
import threading
import time
import asyncio
from bleak import BleakClient, BleakScanner
from pydexcom import Dexcom

# BLE UUIDs - must match the ones in the Arduino code
MOTOR_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
MOTOR_CHARACTERISTIC_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
DEVICE_NAME = "ESP32_MOTOR_CTRL"


# Global connection state to share between pages
class ConnectionState:
    device_address = None
    is_connected = False
    connection_message = "Not connected"
    client = None
    last_scan_results = []

    # Dexcom connection state
    dexcom_client = None
    dexcom_username = None
    dexcom_password = None
    dexcom_connected = False
    dexcom_sensor_start = None


# Singleton connection state
connection_state = ConnectionState()


def create_connections_tab(app):
    """Create and populate the connections tab content."""
    # Create a scroll container with vertical scrolling only.
    scroll_container = toga.ScrollContainer(horizontal=False, style=Pack(flex=1))

    # Main box with uniform gray background.
    main_content = toga.Box(
        style=Pack(
            direction=COLUMN,
            margin=15,
            background_color='#F0F0F0',  # Uniform light gray background.
            flex=1
        )
    )

    # First panel - Dexcom G7 Account.
    dexcom_panel = create_device_panel(
        "Dexcom G7 Account",
        "Disconnected",  # Initial status.
        "",  # Empty detail_text initially
        ["Connect Dexcom Account", "Unlink Account"],
        "dexcom",  # Panel type for styling.
        app  # Pass the app instance.
    )
    main_content.add(dexcom_panel)

    # Store the dexcom panel for updates
    connection_state.dexcom_panel = dexcom_panel

    # Reduced spacing between panels.
    main_content.add(toga.Box(style=Pack(height=5, background_color='#F0F0F0')))

    # Second panel - Glucagon Infusion Pump.
    pump_panel = create_device_panel(
        "Glucagon Infusion Pump",
        "Disconnected",  # Initial status.
        None,  # No sensor start date.
        ["Connect Pump", "Disconnect Pump"],
        "pump",  # Panel type for styling.
        app  # Pass the app instance.
    )
    main_content.add(pump_panel)

    # BLE Scan Results Panel
    scan_results_panel = toga.Box(
        style=Pack(
            direction=COLUMN,
            margin=10,
            background_color='white',
            width=340
        )
    )

    scan_results_title = toga.Label(
        "BLE Scan Results",
        style=Pack(
            font_size=18,
            font_weight='bold',
            text_align=LEFT,
            margin_bottom=5,
            background_color='white'
        )
    )
    scan_results_panel.add(scan_results_title)

    # Results container
    scan_results_label = toga.MultilineTextInput(
        readonly=True,
        style=Pack(
            height=100,
            background_color='white',
            width=320
        )
    )
    scan_results_panel.add(scan_results_label)
    scan_results_panel.scan_results = scan_results_label

    # Store panel reference in connection_state for updates
    connection_state.scan_results_panel = scan_results_panel

    main_content.add(toga.Box(style=Pack(height=5, background_color='#F0F0F0')))
    main_content.add(scan_results_panel)

    # Store panel reference in connection_state for updates
    connection_state.pump_panel = pump_panel

    # Set up the scroll container.
    scroll_container.content = main_content
    app.content_box.add(scroll_container)

    # Start the background task to monitor connection status
    # Using asyncio.create_task instead of deprecated app.add_background_task
    asyncio.create_task(update_connection_status(app))

    return scroll_container


def create_device_panel(title, status, detail_text=None, button_texts=None, panel_type="default", app_instance=None):
    """Create a white panel for device information.

    Args:
        title: The title of the panel.
        status: Status text.
        detail_text: Optional detail text.
        button_texts: List of button text strings.
        panel_type: Type of panel ('dexcom' or 'pump') for styling.
        app_instance: The application instance.
    """
    # Panel container with white background.
    panel = toga.Box(
        style=Pack(
            direction=COLUMN,
            margin=10,  # Reduced overall panel margin.
            background_color='white',
            width=340  # Maximum width now set to 340.
        )
    )

    # Title.
    title_label = toga.Label(
        title,
        style=Pack(
            font_size=18,
            font_weight='bold',
            text_align=LEFT,
            margin_bottom=5,  # Reduced spacing beneath title.
            background_color='white'
        )
    )
    panel.add(title_label)

    # Status row.
    status_box = toga.Box(
        style=Pack(
            direction=ROW,
            margin=(0, 0, 4, 0),  # Reduced vertical margin.
            background_color='white'
        )
    )

    status_label = toga.Label(
        "Status:",
        style=Pack(
            font_size=14,
            font_weight='bold',
            text_align=LEFT,
            background_color='white'
        )
    )

    # For dexcom and pump panels, override status to "Disconnected" in red.
    if panel_type in ["dexcom", "pump"]:
        initial_status = "Disconnected"
        status_color = "red"
    else:
        initial_status = status
        status_color = "#4CAF50"  # Green.

    status_value = toga.Label(
        initial_status,
        style=Pack(
            font_size=14,
            font_weight='bold',
            text_align=LEFT,
            margin_left=8,
            color=status_color,
            background_color='white'
        )
    )
    # Store the status label for later updates.
    panel.status_value = status_value

    status_box.add(status_label)
    status_box.add(status_value)
    panel.add(status_box)

    # Detail text (if provided).
    if detail_text is not None:
        detail_label = toga.Label(
            detail_text,
            style=Pack(
                font_size=14,
                text_align=LEFT,
                margin_bottom=5,  # Reduced spacing beneath detail text.
                background_color='white'
            )
        )
        panel.add(detail_label)
        # Store detail label for updates
        panel.detail_label = detail_label

    # Add buttons.
    if button_texts:
        for button_text in button_texts:
            # Set button colors based on panel type.
            if panel_type == "dexcom":
                button_color = '#003366'  # Navy blue.
            elif panel_type == "pump":
                button_color = '#FF6600'  # Dark orange.
            else:
                button_color = '#D3D3D3'

            button = toga.Button(
                button_text,
                on_press=lambda widget, text=button_text, p=panel, a=app_instance: handle_button_press(text, p, a),
                style=Pack(
                    margin=6,  # Reduced margin.
                    background_color=button_color,
                    color='white',
                    width=320,
                    font_size=10  # Button text size.
                )
            )
            panel.add(button)
            # Reduced space between buttons.
            if button_text != button_texts[-1]:
                panel.add(toga.Box(style=Pack(height=4, background_color='white')))

    return panel


def handle_button_press(button_text, panel, app):
    """Handle button press events."""
    print(f"Button pressed: {button_text}")
    if button_text == "Connect Dexcom Account":
        open_dexcom_connection_window(app, panel)
    elif button_text == "Unlink Account":
        disconnect_dexcom(panel)
    elif button_text.lower() == "connect pump":
        panel.status_value.text = "Scanning..."
        panel.status_value.style.color = "blue"
        asyncio.create_task(scan_for_ble_devices(app, panel))
    elif button_text.lower() == "disconnect pump":
        panel.status_value.text = "Disconnecting..."
        panel.status_value.style.color = "blue"
        asyncio.create_task(disconnect_pump(panel))


def disconnect_dexcom(panel):
    """Disconnect from Dexcom account."""
    if connection_state.dexcom_client:
        connection_state.dexcom_client = None
        connection_state.dexcom_username = None
        connection_state.dexcom_password = None
        connection_state.dexcom_connected = False

        # Update panel
        panel.status_value.text = "Disconnected"
        panel.status_value.style.color = "red"
        if hasattr(panel, 'detail_label'):
            panel.detail_label.text = ""  # Clear the detail text when disconnected

        print("Dexcom account unlinked")


async def scan_for_ble_devices(app, panel):
    """Scan for BLE devices and attempt to connect to the pump."""
    if connection_state.scan_results_panel is not None:
        connection_state.scan_results_panel.scan_results.value = "Scanning for BLE devices...\n"

    try:
        # Scan for devices
        devices = await BleakScanner.discover()

        # Reset scan results
        found_devices = []
        target_found = False

        # Process scan results
        for device in devices:
            device_name = device.name or "Unknown"
            device_addr = device.address
            found_devices.append(f"{device_name}: {device_addr}")

            if device.name and DEVICE_NAME in device.name:
                connection_state.device_address = device.address
                target_found = True

        # Update scan results display
        if connection_state.scan_results_panel is not None:
            connection_state.scan_results_panel.scan_results.value = "\n".join(
                found_devices) if found_devices else "No BLE devices found"

        # If we found our target device, attempt to connect
        if target_found:
            panel.status_value.text = f"Found pump at {connection_state.device_address}. Connecting..."
            await connect_to_pump(panel)
        else:
            panel.status_value.text = "Pump not found"
            panel.status_value.style.color = "red"

    except Exception as e:
        error_msg = f"Scan error: {str(e)}"
        print(error_msg)
        panel.status_value.text = "Scan error"
        panel.status_value.style.color = "red"
        if connection_state.scan_results_panel is not None:
            connection_state.scan_results_panel.scan_results.value += f"\n{error_msg}"


async def connect_to_pump(panel):
    """Connect to the BLE pump device."""
    if not connection_state.device_address:
        panel.status_value.text = "No device address"
        panel.status_value.style.color = "red"
        return

    try:
        # Create client and connect
        client = BleakClient(connection_state.device_address)
        await client.connect()

        # Check if we have the required service and characteristic
        services = await client.get_services()
        found_characteristic = False

        for service in services:
            for char in service.characteristics:
                if char.uuid.lower() == MOTOR_CHARACTERISTIC_UUID.lower():
                    found_characteristic = True

        if not found_characteristic:
            # Close connection if we don't have the required characteristic
            await client.disconnect()
            panel.status_value.text = "Incompatible device"
            panel.status_value.style.color = "red"
            return

        # Successfully connected
        connection_state.client = client
        connection_state.is_connected = True
        connection_state.connection_message = "Connected"
        panel.status_value.text = "Connected"
        panel.status_value.style.color = "green"

    except Exception as e:
        error_msg = f"Connection error: {str(e)}"
        print(error_msg)
        panel.status_value.text = "Connection failed"
        panel.status_value.style.color = "red"
        if connection_state.scan_results_panel is not None:
            connection_state.scan_results_panel.scan_results.value += f"\n{error_msg}"
        connection_state.is_connected = False
        connection_state.client = None


async def disconnect_pump(panel):
    """Disconnect from the BLE pump device."""
    try:
        if connection_state.client and connection_state.is_connected:
            await connection_state.client.disconnect()

        connection_state.client = None
        connection_state.is_connected = False
        connection_state.connection_message = "Disconnected"
        panel.status_value.text = "Disconnected"
        panel.status_value.style.color = "red"

    except Exception as e:
        error_msg = f"Disconnect error: {str(e)}"
        print(error_msg)
        panel.status_value.text = "Disconnect error"
        panel.status_value.style.color = "red"
        if connection_state.scan_results_panel is not None:
            connection_state.scan_results_panel.scan_results.value += f"\n{error_msg}"


async def update_connection_status(app):
    """Background task to monitor BLE connection status."""
    while True:
        # If we have a client but it's disconnected, update UI
        if connection_state.client is not None and connection_state.is_connected:
            try:
                # Check if client is still connected (will raise exception if not)
                is_connected = connection_state.client.is_connected
                if not is_connected:
                    connection_state.is_connected = False
                    connection_state.connection_message = "Disconnected"
                    if connection_state.pump_panel is not None:
                        connection_state.pump_panel.status_value.text = "Disconnected"
                        connection_state.pump_panel.status_value.style.color = "red"
            except Exception:
                # Connection lost
                connection_state.is_connected = False
                connection_state.connection_message = "Connection lost"
                if connection_state.pump_panel is not None:
                    connection_state.pump_panel.status_value.text = "Connection lost"
                    connection_state.pump_panel.status_value.style.color = "red"

        # Check Dexcom connection periodically (fetch current reading to test connection)
        if connection_state.dexcom_client and connection_state.dexcom_connected:
            try:
                # Try to get a reading to verify the connection is still working
                reading = connection_state.dexcom_client.get_current_glucose_reading()
                if reading:
                    # Connection is still good, update the reading time
                    if connection_state.dexcom_panel:
                        sensor_date = reading.datetime.strftime('%m/%d/%y, %I:%M %p')
                        if hasattr(connection_state.dexcom_panel, 'detail_label'):
                            # Keep the original sensor start time but update the last reading
                            if connection_state.dexcom_panel.detail_label.text.startswith("Sensor Start:"):
                                # Extract existing sensor start time
                                sensor_start = connection_state.dexcom_panel.detail_label.text.split("\n")[0]
                                # Update with current reading time
                                connection_state.dexcom_panel.detail_label.text = f"{sensor_start}\nLast Reading: {sensor_date}"
                            else:
                                # If no sensor start time exists, add it now
                                current_time = time.strftime('%m/%d/%y, %I:%M %p')
                                connection_state.dexcom_panel.detail_label.text = f"Sensor Start: {current_time}\nLast Reading: {sensor_date}"
            except Exception as e:
                # Connection issue with Dexcom
                print(f"Dexcom connection error: {str(e)}")
                connection_state.dexcom_connected = False
                if connection_state.dexcom_panel:
                    connection_state.dexcom_panel.status_value.text = "Connection lost"
                    connection_state.dexcom_panel.status_value.style.color = "red"

        # Wait before checking again
        await asyncio.sleep(5)


def open_dexcom_connection_window(app, panel):
    """Open a new window for Dexcom account connection details."""
    conn_window = toga.Window(title="Connect Dexcom Account", size=(350, 350))
    main_box = toga.Box(
        style=Pack(direction=COLUMN, margin=10, background_color='white', width=330)
    )

    # Header description
    header_label = toga.Label(
        "Enter your Dexcom Share credentials",
        style=Pack(font_size=16, font_weight='bold', margin_bottom=10, color='black')
    )
    main_box.add(header_label)

    # Information about credential types
    info_label = toga.Label(
        "You can use your username or phone number",
        style=Pack(color='black', margin_bottom=10)
    )
    main_box.add(info_label)

    # Set field widths
    label_width = 100
    input_width = 220

    # Username or Phone field with selection
    username_type_box = toga.Box(style=Pack(direction=ROW, margin_bottom=5))
    username_type_label = toga.Label("Credential Type:", style=Pack(color='black', width=label_width))
    username_type = toga.Selection(
        items=["Email", "Phone Number", "Account ID"],
        style=Pack(width=input_width)
    )
    username_type_box.add(username_type_label)
    username_type_box.add(username_type)
    main_box.add(username_type_box)

    # Username field error
    user_error = toga.Label("", style=Pack(color='red', height=15))
    main_box.add(user_error)

    # Username field
    user_box = toga.Box(style=Pack(direction=ROW, margin_bottom=5))
    user_label = toga.Label("Username:", style=Pack(color='black', width=label_width))
    user_input = toga.TextInput(placeholder="Email/Phone/Account ID", style=Pack(width=input_width))
    user_box.add(user_label)
    user_box.add(user_input)
    main_box.add(user_box)

    # Password field error
    pass_error = toga.Label("", style=Pack(color='red', height=15))
    main_box.add(pass_error)

    # Password field
    pass_box = toga.Box(style=Pack(direction=ROW, margin_bottom=10))
    pass_label = toga.Label("Password:", style=Pack(color='black', width=label_width))
    pass_input = toga.PasswordInput(placeholder="Enter password", style=Pack(width=input_width))
    pass_box.add(pass_label)
    pass_box.add(pass_input)
    main_box.add(pass_box)

    # Format info based on selection - removed italic styling which caused the error
    format_info = toga.Label(
        "Format: user@example.com",
        style=Pack(color='gray', margin_bottom=10)
    )
    main_box.add(format_info)

    # Update format info when selection changes
    def update_format_info(widget):
        selection = username_type.value
        if selection == "Email":
            format_info.text = "Format: user@example.com"
            user_label.text = "Email:"
            user_input.placeholder = "Enter email address"
        elif selection == "Phone Number":
            format_info.text = "Format: +11234567890 (include country code)"
            user_label.text = "Phone:"
            user_input.placeholder = "Enter phone with country code"
        else:  # Account ID
            format_info.text = "Format: 12345678-90ab-cdef-1234-567890abcdef"
            user_label.text = "Account ID:"
            user_input.placeholder = "Enter Dexcom account ID"

    username_type.on_change = update_format_info

    # Buttons container.
    btn_box = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=10))
    connect_button = toga.Button(
        "Connect",
        on_press=lambda w: dexcom_connect_handler(
            app, conn_window, panel,
            username_type, user_input, pass_input,
            user_error, pass_error
        ),
        style=Pack(background_color='#003366', color='white', margin=10, width=110)
    )
    cancel_button = toga.Button(
        "Cancel",
        on_press=lambda w: conn_window.close(),
        style=Pack(background_color='#666666', color='white', margin=10, width=110)
    )
    btn_box.add(connect_button)
    btn_box.add(toga.Box(style=Pack(width=20)))  # Spacer.
    btn_box.add(cancel_button)
    main_box.add(btn_box)

    conn_window.content = main_box
    app.windows.add(conn_window)
    conn_window.show()


def dexcom_connect_handler(app, window, panel, username_type, user_input, pass_input,
                           user_error, pass_error):
    """Handle Dexcom connection form submission."""
    # Get form values
    credential_type = username_type.value
    username = user_input.value.strip()
    password = pass_input.value.strip()

    # Validate inputs
    error = False
    if not username:
        user_error.text = "Error: Username is required"
        error = True
    else:
        user_error.text = ""

    if not password:
        pass_error.text = "Error: Password is required"
        error = True
    else:
        pass_error.text = ""

    if error:
        return

    # Update UI to show connecting status
    panel.status_value.text = "Connecting..."
    panel.status_value.style.color = "blue"

    # Format the username based on type
    formatted_username = username
    account_id = None

    if credential_type == "Phone Number" and not username.startswith("+"):
        formatted_username = f"+{username}"

    if credential_type == "Account ID":
        account_id = username
        formatted_username = None

    # Create connection thread to avoid UI freeze
    def connect_dexcom():
        try:
            # Connect to Dexcom using pydexcom
            if account_id:
                dexcom_client = Dexcom(account_id=account_id, password=password)
            else:
                dexcom_client = Dexcom(username=formatted_username, password=password)

            # Try to get a reading to verify connection works
            reading = dexcom_client.get_current_glucose_reading()

            if reading:
                # Store the connection globally
                connection_state.dexcom_client = dexcom_client
                connection_state.dexcom_username = formatted_username or account_id
                connection_state.dexcom_password = password
                connection_state.dexcom_connected = True

                # Format reading time for display
                reading_time = reading.datetime.strftime('%m/%d/%y, %I:%M %p')

                # Update UI on the main thread
                app.loop.call_soon_threadsafe(lambda: update_dexcom_ui(
                    panel,
                    connected=True,
                    reading_time=reading_time,
                    glucose_value=reading.value
                ))

                print(f"Successfully connected to Dexcom. Current reading: {reading.value} mg/dL")
            else:
                # No reading available
                app.loop.call_soon_threadsafe(lambda: update_dexcom_ui(
                    panel,
                    connected=False,
                    error="No glucose readings available"
                ))

        except Exception as e:
            # Connection failed
            error_msg = str(e)
            print(f"Dexcom connection error: {error_msg}")

            app.loop.call_soon_threadsafe(lambda: update_dexcom_ui(
                panel,
                connected=False,
                error=error_msg
            ))

    # Start connection thread
    threading.Thread(target=connect_dexcom, daemon=True).start()

    # Close the dialog
    window.close()


def update_dexcom_ui(panel, connected, reading_time=None, glucose_value=None, error=None):
    """Update the Dexcom panel UI after connection attempt."""
    if connected:
        # Connection successful
        panel.status_value.text = "Connected"
        panel.status_value.style.color = "green"

        # Set the sensor start time to the current time when connection is made
        current_time = time.strftime('%m/%d/%y, %I:%M %p')

        if hasattr(panel, 'detail_label'):
            # Set the connection time as the sensor start time
            panel.detail_label.text = f"Sensor Start: {current_time}"

            # Add reading time if available
            if reading_time:
                panel.detail_label.text += f"\nLast Reading: {reading_time}"

        # Show success dialog with current reading
        if glucose_value is not None:
            connection_state.dexcom_panel.app.main_window.info_dialog(
                "Dexcom Connected",
                f"Successfully connected to Dexcom.\nCurrent glucose: {glucose_value} mg/dL"
            )
    else:
        # Connection failed
        panel.status_value.text = "Connection Failed"
        panel.status_value.style.color = "red"

        # Show error dialog
        error_message = error or "Could not connect to Dexcom. Check your credentials and try again."

        if "invalid password" in error_message.lower():
            error_message = "Invalid credentials. Please check your username and password."

        connection_state.dexcom_panel.app.main_window.error_dialog(
            "Dexcom Connection Error",
            error_message
        )


def find_devices(app):
    """Handle the find devices button press."""
    print("Looking for glucose monitoring devices...")
    app.main_window.info_dialog(
        'Searching for Devices',
        'Searching for nearby glucose monitoring devices...'
    )