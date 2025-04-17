import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER


def open_dexcom_session_dialog(app, on_submit):
    """
    Open a dialog to enter Dexcom credentials for starting a CGM session.

    Args:
        app: The Toga application instance
        on_submit: Callback function that receives username and password
    """
    # Import connection_state to check for existing credentials
    from ..tabs.connections import connection_state

    session_window = toga.Window(title="Connect to Dexcom CGM", size=(350, 250))

    main_box = toga.Box(
        style=Pack(
            direction=COLUMN,
            margin=10,
            background_color='white'
        )
    )

    # Title
    title_label = toga.Label(
        "Start Dexcom CGM Session",
        style=Pack(
            font_size=16,
            font_weight='bold',
            text_align='center',
            margin_bottom=10
        )
    )
    main_box.add(title_label)

    # Check if we already have credentials
    has_existing_connection = (connection_state.dexcom_client is not None and
                               connection_state.dexcom_connected)

    if has_existing_connection:
        info_text = "Using existing Dexcom connection"
        if connection_state.dexcom_username:
            info_text += f" ({connection_state.dexcom_username})"

        info_label = toga.Label(
            info_text,
            style=Pack(
                color='green',
                margin_bottom=20,
                text_align='center'
            )
        )
        main_box.add(info_label)

        # Button to use existing connection
        use_existing_button = toga.Button(
            "Use Existing Connection",
            on_press=lambda w: handle_existing_connection(session_window, on_submit),
            style=Pack(
                background_color='#003366',
                color='white',
                margin=10,
                width=200
            )
        )

        # Center the button
        button_box = toga.Box(style=Pack(
            direction=ROW,
            align_items=CENTER
        ))
        button_box.add(use_existing_button)
        main_box.add(button_box)

        # Button to use new credentials
        new_creds_button = toga.Button(
            "Enter New Credentials",
            on_press=lambda w: show_credentials_form(),
            style=Pack(
                background_color='#666666',
                color='white',
                margin=10,
                width=200
            )
        )

        # Center the button
        button_box2 = toga.Box(style=Pack(
            direction=ROW,
            align_items=CENTER
        ))
        button_box2.add(new_creds_button)
        main_box.add(button_box2)

        # Credentials form container (initially hidden)
        creds_form = toga.Box(
            style=Pack(
                direction=COLUMN,
                visibility='hidden',
                display='none'
            )
        )
        main_box.add(creds_form)
    else:
        # No existing credentials, show form directly
        creds_form = main_box

    # Username field
    user_error = toga.Label("", style=Pack(color='red', height=15))
    user_label = toga.Label("Username:", style=Pack(color='black'))
    user_input = toga.TextInput(
        placeholder="Email or phone with country code",
        style=Pack(width=330)
    )

    # Password field
    pass_error = toga.Label("", style=Pack(color='red', height=15))
    pass_label = toga.Label("Password:", style=Pack(color='black'))
    pass_input = toga.PasswordInput(
        placeholder="Enter password",
        style=Pack(width=330)
    )

    creds_form.add(user_error)
    creds_form.add(user_label)
    creds_form.add(user_input)
    creds_form.add(pass_error)
    creds_form.add(pass_label)
    creds_form.add(pass_input)

    # Buttons container for credentials form
    creds_btn_box = toga.Box(style=Pack(
        direction=ROW,
        align_items=CENTER,
        margin_top=15
    ))

    def handle_submit(widget):
        # Validate inputs
        username = user_input.value.strip()
        password = pass_input.value.strip()
        error = False

        if not username:
            user_error.text = "Username is required"
            error = True
        else:
            user_error.text = ""

        if not password:
            pass_error.text = "Password is required"
            error = True
        else:
            pass_error.text = ""

        if not error:
            # Close the window and call the submit callback
            session_window.close()
            on_submit(username, password)

    # Connect and Cancel buttons
    connect_button = toga.Button(
        "Connect",
        on_press=handle_submit,
        style=Pack(
            background_color='#003366',
            color='white',
            margin=5,
            width=120
        )
    )

    cancel_button = toga.Button(
        "Cancel",
        on_press=lambda w: session_window.close(),
        style=Pack(
            background_color='#666666',
            color='white',
            margin=5,
            width=120
        )
    )

    creds_btn_box.add(connect_button)
    creds_btn_box.add(toga.Box(style=Pack(width=10)))  # Spacer
    creds_btn_box.add(cancel_button)
    creds_form.add(creds_btn_box)

    # Function to show credentials form
    def show_credentials_form():
        if has_existing_connection:
            info_label.text = "Enter new Dexcom credentials"
            info_label.style.color = "black"
            use_existing_button.style.visibility = "hidden"
            use_existing_button.style.display = "none"
            new_creds_button.style.visibility = "hidden"
            new_creds_button.style.display = "none"
            creds_form.style.visibility = "visible"
            creds_form.style.display = "flex"

    # Function to handle using existing connection
    def handle_existing_connection(window, callback):
        window.close()
        # Pass the existing credentials to the callback
        callback(connection_state.dexcom_username, connection_state.dexcom_password)

    session_window.content = main_box
    app.windows.add(session_window)
    session_window.show()

    return session_window