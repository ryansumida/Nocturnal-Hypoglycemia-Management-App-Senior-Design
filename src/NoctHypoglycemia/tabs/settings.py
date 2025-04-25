import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER, LEFT
from ..utils.firebase_manager import firebase_manager


def create_settings_tab(app):
    """Create and populate the settings tab content."""
    # Create a scroll container with vertical scrolling only.
    scroll_container = toga.ScrollContainer(horizontal=False, style=Pack(flex=1))

    # Main box with uniform gray background.
    main_content = toga.Box(
        style=Pack(
            direction=COLUMN,
            margin=5,  # Reduced margin
            background_color='#F0F0F0',
            flex=1,
            width=340  # Set maximum width
        )
    )

    # Profile section.
    profile_heading = toga.Label(
        'Profile',
        style=Pack(
            font_size=18,
            font_weight='bold',
            margin=(0, 0, 1, 0),  # Minimal bottom margin
            background_color='#F0F0F0'
        )
    )
    main_content.add(profile_heading)

    # Emergency Contact (row label remains unbolded, size 12).
    app.emergency_input = toga.TextInput(
        value=app.settings['emergency_contact'],
        placeholder='(111)-111-1111',
        style=Pack(background_color='white')
    )
    emergency_box = create_setting_row(
        'Emergency Contact:',
        app.emergency_input,
        ''
    )
    main_content.add(emergency_box)

    # Reduced spacer.
    main_content.add(toga.Box(style=Pack(height=8, background_color='#F0F0F0')))

    # App Settings section.
    app_settings_heading = toga.Label(
        'App Settings',
        style=Pack(
            font_size=18,
            font_weight='bold',
            margin=(0, 0, 1, 0),  # Minimal bottom margin
            background_color='#F0F0F0'
        )
    )
    main_content.add(app_settings_heading)

    # Hyperglycemia Threshold.
    app.hyper_input = toga.TextInput(
        value=app.settings['hyperglycemia_threshold'],
        placeholder='180',
        style=Pack(background_color='white')
    )
    hyper_box = create_setting_row(
        'Hyperglycemia Threshold:',
        app.hyper_input,
        'mg/dL'
    )
    main_content.add(hyper_box)

    # Mild Hypoglycemia Threshold.
    app.hypo_input = toga.TextInput(
        value=app.settings['hypoglycemia_threshold'],
        placeholder='70',
        style=Pack(background_color='white')
    )
    hypo_box = create_setting_row(
        'Mild Hypoglycemia Threshold:',
        app.hypo_input,
        'mg/dL'
    )
    main_content.add(hypo_box)

    # Severe Hypoglycemia Threshold.
    app.severe_hypo_input = toga.TextInput(
        value=app.settings.get('severe_hypoglycemia_threshold', "54"),
        placeholder='54',
        style=Pack(background_color='white')
    )
    infusion_max_box = create_setting_row(
        'Severe Hypoglycemia Threshold:',
        app.severe_hypo_input,
        'mg/dL'
    )
    main_content.add(infusion_max_box)

    # Alert Volume (consolidated from previous alert_volume and alarm_volume).
    app.volume_input = toga.Selection(
        items=['Low', 'Medium', 'High'],
        value=app.settings['alert_volume'],
        style=Pack(background_color='white')
    )
    volume_box = create_setting_row(
        'Alert Volume:',
        app.volume_input,
        ''
    )
    main_content.add(volume_box)

    # Reduced spacer.
    main_content.add(toga.Box(style=Pack(height=8, background_color='#F0F0F0')))

    # Infusion Pump Settings section.
    pump_heading = toga.Label(
        'Infusion Pump Settings',
        style=Pack(
            font_size=18,
            font_weight='bold',
            margin=(0, 0, 1, 0),  # Minimal bottom margin
            background_color='#F0F0F0'
        )
    )
    main_content.add(pump_heading)

    # Glucagon Dosage (changed units from mg to mL).
    app.glucagon_input = toga.TextInput(
        value=app.settings['glucagon_dosage'],
        placeholder='0.2',
        style=Pack(background_color='white')
    )
    glucagon_box = create_setting_row(
        'Glucagon Dosage (5 mg/mL):',
        app.glucagon_input,
        'mL'  # Changed from 'mg' to 'mL'
    )
    main_content.add(glucagon_box)

    # Minimal spacer before protocols section
    main_content.add(toga.Box(style=Pack(height=5, background_color='#F0F0F0')))

    # Protocols Section Heading with line break.
    protocols_heading = toga.Label(
        'Protocols with Default\nThresholds',
        style=Pack(
            font_size=18,
            font_weight='bold',
            margin=(0, 0, 0, 0),  # No bottom margin at all
            background_color='#F0F0F0'
        )
    )
    main_content.add(protocols_heading)

    # Blood Glucose Valid Range box (red) - with negative top margin to reduce space
    bg_range_box = toga.Box(
        style=Pack(
            direction=COLUMN,
            background_color='#8B0000',
            margin=(-2, 0, 2, 0),  # Negative top margin to pull up closer to header
            width=320,
            height=50  # Explicit height
        )
    )
    bg_range_label = toga.Label(
        "Blood Glucose Valid Range (40-400 mg/dL):\n- Values outside this range are invalid",
        style=Pack(
            color='white',
            font_size=12,
            text_align=LEFT,
            width=320,
            background_color='#8B0000',
            padding=(3, 4, 3, 4)  # Medium padding for content
        )
    )
    bg_range_box.add(bg_range_label)
    main_content.add(bg_range_box)

    # Hyperglycemia protocol box - with explicit height
    hyper_protocol_box = toga.Box(
        style=Pack(
            direction=COLUMN,
            background_color='darkorange',
            margin=(0, 0, 2, 0),
            width=320,
            height=70  # Explicit height
        )
    )
    hyper_protocol_label = toga.Label(
        "Hyperglycemia (181-400 mg/dL):\n- 5 min High Glucose Alarm\n- Emergency Contact Notified",
        style=Pack(
            color='white',
            font_size=12,
            text_align=LEFT,
            width=320,
            background_color='darkorange',
            padding=(3, 4, 3, 4)  # Medium padding
        )
    )
    hyper_protocol_box.add(hyper_protocol_label)
    main_content.add(hyper_protocol_box)

    # Safe Range protocol box (green) - with explicit height
    safe_range_box = toga.Box(
        style=Pack(
            direction=COLUMN,
            background_color='green',
            margin=(0, 0, 2, 0),
            width=320,
            height=30  # Explicit height
        )
    )
    safe_range_label = toga.Label(
        "Safe Range (70-180 mg/dL)",
        style=Pack(
            color='white',
            font_size=12,
            text_align=LEFT,
            width=320,
            background_color='green',
            padding=(3, 4, 3, 4)  # Medium padding
        )
    )
    safe_range_box.add(safe_range_label)
    main_content.add(safe_range_box)

    # Mild Hypoglycemia protocol box - with explicit height
    mild_protocol_box = toga.Box(
        style=Pack(
            direction=COLUMN,
            background_color='goldenrod',
            margin=(0, 0, 2, 0),
            width=320,
            height=70  # Explicit height
        )
    )
    mild_protocol_label = toga.Label(
        "Mild Hypoglycemia (54-69 mg/dL):\n- 5 min Low Glucose Alarm\n- App recommends eating 15g of carbs",
        style=Pack(
            color='white',
            font_size=12,
            text_align=LEFT,
            width=320,
            background_color='goldenrod',
            padding=(3, 4, 3, 4)  # Medium padding
        )
    )
    mild_protocol_box.add(mild_protocol_label)
    main_content.add(mild_protocol_box)

    # Severe Hypoglycemia protocol box - with explicit height
    severe_protocol_box = toga.Box(
        style=Pack(
            direction=COLUMN,
            background_color='darkblue',
            margin=(0, 0, 2, 0),
            width=320,
            height=100  # Explicit height
        )
    )
    severe_protocol_label = toga.Label(
        "Severe Hypoglycemia (40-54 mg/dL):\n- 15 min Low Glucose Alarm\n- 1 dose of glucagon infused\n- Emergency Contact Notified",
        style=Pack(
            color='white',
            font_size=12,
            text_align=LEFT,
            width=320,
            background_color='darkblue',
            padding=(3, 4, 3, 4)  # Medium padding
        )
    )
    severe_protocol_box.add(severe_protocol_label)
    main_content.add(severe_protocol_box)

    # Reduced spacer before buttons.
    main_content.add(toga.Box(style=Pack(height=12, background_color='#F0F0F0')))

    # Save button container.
    save_button_box = toga.Box(
        style=Pack(
            direction=COLUMN,
            align_items=CENTER,
            background_color='#F0F0F0',
            margin=(5, 0, 5, 0)  # Reduced margin
        )
    )
    save_button = toga.Button(
        'Save Settings',
        on_press=lambda widget: save_settings(app),
        style=Pack(margin=5, width=160, height=35, font_size=14)  # Reduced margin and height
    )
    save_button_box.add(save_button)
    main_content.add(save_button_box)

    # Reduced spacer before logout button.
    main_content.add(toga.Box(style=Pack(height=5, background_color='#F0F0F0')))

    # Logout button container.
    logout_button_box = toga.Box(
        style=Pack(
            direction=COLUMN,
            align_items=CENTER,
            background_color='#F0F0F0',
            margin=(0, 0, 10, 0)  # Reduced margin
        )
    )
    logout_button = toga.Button(
        'Log Out',
        on_press=lambda widget: handle_logout(app),
        style=Pack(
            margin=5,  # Reduced margin
            width=160,
            height=35,  # Reduced height
            font_size=14,
            background_color='#D32F2F',
            color='white'
        )
    )
    logout_button_box.add(logout_button)
    main_content.add(logout_button_box)

    # Add small spacer before Clear History button
    main_content.add(toga.Box(style=Pack(height=15, background_color='#F0F0F0')))

    # Clear History button container
    clear_history_box = toga.Box(
        style=Pack(
            direction=COLUMN,
            align_items=CENTER,
            background_color='#F0F0F0',
            margin=(0, 0, 10, 0)
        )
    )
    clear_history_button = toga.Button(
        'Clear 10 Day History',
        on_press=lambda widget: clear_firebase_history(app),
        style=Pack(
            margin=5,
            width=200,  # Increased from 160 to 200
            height=35,
            font_size=14,
            background_color='#FF6600',
            color='white'
        )
    )
    clear_history_box.add(clear_history_button)
    main_content.add(clear_history_box)

    # Set up the scroll container.
    scroll_container.content = main_content
    app.content_box.add(scroll_container)


def create_setting_row(label_text, input_widget, units_text):
    """Create a row with a label, input widget, and units label."""
    label = toga.Label(
        label_text,
        style=Pack(
            width=150,  # Reduced width
            text_align=LEFT,
            margin=(3, 3),  # Reduced margin
            background_color='#F0F0F0',
            font_size=12
        )
    )

    spacer = toga.Box(style=Pack(flex=0.1, background_color='#F0F0F0'))  # Reduced spacer
    input_container = toga.Box(
        style=Pack(
            direction=ROW,
            background_color='#F0F0F0',
            margin=(1, 3),  # Reduced margin
            width=100  # Reduced width
        )
    )
    input_widget.style.update(flex=1)
    input_container.add(input_widget)

    units = toga.Label(
        units_text,
        style=Pack(
            width=60,  # Reduced width
            text_align=LEFT,
            margin=(3, 0, 0, 0),  # Reduced margin
            background_color='#F0F0F0'
        )
    )

    row = toga.Box(
        style=Pack(
            direction=ROW,
            margin=(3, 0),  # Reduced margin
            align_items=CENTER,
            background_color='#F0F0F0'
        )
    )
    row.add(label)
    row.add(spacer)
    row.add(input_container)
    row.add(units)
    return row


def save_settings(app):
    """Handle the save settings button press."""
    app.settings['emergency_contact'] = app.emergency_input.value
    app.settings['hyperglycemia_threshold'] = app.hyper_input.value
    app.settings['hypoglycemia_threshold'] = app.hypo_input.value
    app.settings['severe_hypoglycemia_threshold'] = app.severe_hypo_input.value
    app.settings['alert_volume'] = app.volume_input.value
    # Store alert_volume in both settings to maintain compatibility
    app.settings['alarm_volume'] = app.volume_input.value.lower()  # Save in lowercase for protocols
    app.settings['glucagon_dosage'] = app.glucagon_input.value
    app.main_window.info_dialog(
        'Settings Saved',
        'Your settings have been saved successfully!'
    )
    print("Settings saved:", app.settings)


def handle_logout(app):
    """Handle logout button press."""
    app.just_logged_out = True
    app.show_login()


def clear_firebase_history(app):
    """Clear all glucose sessions from Firebase."""
    # Make sure Firebase is initialized
    if not firebase_manager.db:
        firebase_manager.initialize()

    try:
        # Get a direct reference to the collection
        sessions_ref = firebase_manager.db.collection('glucose_sessions')

        # Get documents with their IDs
        session_docs = sessions_ref.limit(100).get()

        if session_docs:
            count = 0
            for doc in session_docs:
                # Now we have the document with its ID
                doc_id = doc.id
                sessions_ref.document(doc_id).delete()
                count += 1

            app.main_window.info_dialog(
                'History Cleared',
                f'Successfully cleared {count} glucose monitoring sessions.'
            )
        else:
            app.main_window.info_dialog(
                'No Data',
                'No glucose history data found to clear.'
            )
    except Exception as e:
        import traceback
        traceback.print_exc()  # Print detailed error for debugging
        app.main_window.error_dialog(
            'Error',
            f'Error clearing history: {str(e)}'
        )