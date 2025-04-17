import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER
import datetime


class EventHistoryWidget:
    def __init__(self, app):
        self.app = app
        self.container = toga.Box(style=Pack(
            direction=COLUMN,
            padding=10,
            background_color='#F0F0F0',
            width=373
        ))
        self.header = toga.Box(style=Pack(
            direction=ROW,
            padding=(0, 0, 10, 0),
            background_color='#F0F0F0',
            alignment=CENTER
        ))
        self.title = toga.Label('Event History', style=Pack(
            font_size=18,
            font_weight='bold',
            text_align=CENTER,
            background_color='#F0F0F0'
        ))
        self.header.add(self.title)
        self.container.add(self.header)

        # Main content box
        self.content = toga.Box(style=Pack(
            direction=COLUMN,
            padding=10,
            background_color='white',
            width=353,
            alignment=CENTER
        ))

        # Message box
        self.message_box = toga.Box(style=Pack(
            direction=COLUMN,
            padding=5,
            background_color='white',
            width=333
        ))

        # Default message
        self.message = toga.Label(
            'No diabetes events detected',
            style=Pack(
                font_size=16,
                text_align=CENTER,
                background_color='white',
                padding=20
            )
        )

        self.message_box.add(self.message)
        self.content.add(self.message_box)
        self.container.add(self.content)

        # Track events
        self.events = []
        self.current_event = None

    def reset_events(self):
        """Reset all events when a new simulation starts."""
        self.events = []
        self.current_event = None
        self.message.text = 'No diabetes events detected'

    def add_event(self, event_type, start_time, end_time=None, file_name="Unknown"):
        """Add a new diabetes event to the history."""
        # Format the date strings
        start_str = start_time.strftime("%I:%M %p")
        end_str = end_time.strftime("%I:%M %p") if end_time else "Ongoing"

        # Create event text
        event_text = f"{event_type}\nRecorded Start: {file_name}, {start_str}\n"
        if end_time:
            event_text += f"Recorded End: {file_name}, {end_str}"
        else:
            event_text += "Recorded End: Ongoing"

        # Add to events list
        self.events.append(event_text)

        # Update the display message
        if self.events:
            self.message.text = self.events[-1]  # Just show most recent event