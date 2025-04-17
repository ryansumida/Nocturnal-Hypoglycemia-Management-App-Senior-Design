import smtplib
import toga
from email.mime.text import MIMEText

import toga


def send_emergency_sms(app):
    """Simulate sending an emergency SMS to the contact."""
    # Get the emergency contact from settings
    emergency_contact = app.settings['emergency_contact']

    if not emergency_contact:
        app.main_window.info_dialog(
            'No Emergency Contact',
            'Please set an emergency contact in Settings.'
        )
        return

    # Format phone number to ensure it's valid
    # Remove any non-digit characters
    formatted_number = ''.join(c for c in emergency_contact if c.isdigit())

    # Check if it's a valid US number (10 digits)
    if len(formatted_number) != 10:
        app.main_window.info_dialog(
            'Invalid Phone Number',
            'Please enter a valid 10-digit US phone number in Settings.'
        )
        return

    # Since the dialog APIs are in transition, let's use the older method
    # that's still supported (though deprecated)
    try:
        # Show confirmation dialog
        send_sms = app.main_window.confirm_dialog(
            'Send Emergency SMS',
            f'Send emergency SMS to {emergency_contact}?'
        )

        # Handle the result immediately (synchronously)
        if send_sms:
            # This block will execute if user clicked "OK"
            app.main_window.info_dialog(
                'SMS Sent (Simulated)',
                f'Emergency SMS would be sent to {emergency_contact}\n\n'
                f'Message: "Test Emergency Notification from NoctHypoglycemia"'
            )
            print(f"SIMULATION: SMS sent to {formatted_number}")
    except Exception as e:
        # Handle any errors
        print(f"Error in send_emergency_sms: {str(e)}")
        app.main_window.info_dialog(
            'Error',
            f'Could not send SMS: {str(e)}'
        )