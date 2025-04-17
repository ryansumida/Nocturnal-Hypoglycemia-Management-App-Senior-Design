import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER

from NoctHypoglycemia.tabs.glucose import create_glucose_tab
from NoctHypoglycemia.tabs.history import create_history_tab
from NoctHypoglycemia.tabs.connections import create_connections_tab
from NoctHypoglycemia.tabs.settings import create_settings_tab
from NoctHypoglycemia.login import LoginScreen


class Group16(toga.App):
    def startup(self):
        """Construct and show the Toga application."""
        # Initialize settings with default values
        self.settings = {
            'emergency_contact': '',
            'hyperglycemia_threshold': '180',
            'hypoglycemia_threshold': '70',
            'severe_hypoglycemia_threshold': '54',  # Added severe hypoglycemia threshold
            'alert_volume': 'Medium',
            'glucagon_dosage': '0.5'
        }

        self.main_window = toga.MainWindow(title=self.formal_name, size=(393, 852))
        self.show_login()
        self.main_window.show()

    def show_login(self):
        """Display the login screen."""
        self.login_screen = LoginScreen(self, self.on_login_success)
        login_box = self.login_screen.build()
        self.main_window.content = login_box

    def on_login_success(self):
        """Handle successful login by showing the main interface."""
        self.create_main_interface()
        self.show_glucose_tab()

    def create_main_interface(self):
        """Create the main app interface with tabs."""
        main_box = toga.Box(style=Pack(direction=COLUMN, flex=1))
        self.content_box = toga.Box(style=Pack(direction=COLUMN, alignment=CENTER, flex=1))
        tab_bar = toga.Box(style=Pack(direction=ROW, alignment=CENTER, padding=5, height=50, background_color='#F0F0F0'))

        # Create tab buttons with highlighting
        self.glucose_button = toga.Button(
            'Glucose',
            on_press=self.show_glucose_tab,
            style=Pack(flex=1, padding=2, background_color='#FF6600', color='white')
        )
        self.history_button = toga.Button(
            'History',
            on_press=self.show_history_tab,
            style=Pack(flex=1, padding=2)
        )
        self.connections_button = toga.Button(
            'Connections',
            on_press=self.show_connections_tab,
            style=Pack(flex=1, padding=2)
        )
        self.settings_button = toga.Button(
            'Settings',
            on_press=self.show_settings_tab,
            style=Pack(flex=1, padding=2)
        )

        tab_bar.add(self.glucose_button)
        tab_bar.add(self.history_button)
        tab_bar.add(self.connections_button)
        tab_bar.add(self.settings_button)
        main_box.add(self.content_box)
        main_box.add(tab_bar)
        self.main_window.content = main_box

        # Track current tab
        self.current_tab = 'glucose'

    def highlight_current_tab(self):
        """Highlight the currently selected tab."""
        # Reset all buttons
        self.glucose_button.style.background_color = '#EEEEEE'
        self.glucose_button.style.color = 'black'
        self.history_button.style.background_color = '#EEEEEE'
        self.history_button.style.color = 'black'
        self.connections_button.style.background_color = '#EEEEEE'
        self.connections_button.style.color = 'black'
        self.settings_button.style.background_color = '#EEEEEE'
        self.settings_button.style.color = 'black'

        # Highlight current tab
        if self.current_tab == 'glucose':
            self.glucose_button.style.background_color = '#FF6600'
            self.glucose_button.style.color = 'white'
        elif self.current_tab == 'history':
            self.history_button.style.background_color = '#FF6600'
            self.history_button.style.color = 'white'
        elif self.current_tab == 'connections':
            self.connections_button.style.background_color = '#FF6600'
            self.connections_button.style.color = 'white'
        elif self.current_tab == 'settings':
            self.settings_button.style.background_color = '#FF6600'
            self.settings_button.style.color = 'white'

    def clear_content(self):
        """Clear the content area."""
        for child in list(self.content_box.children):
            self.content_box.remove(child)

    def show_glucose_tab(self, widget=None):
        """Show the Glucose tab content."""
        self.clear_content()
        self.current_tab = 'glucose'
        self.highlight_current_tab()
        create_glucose_tab(self)

    def show_history_tab(self, widget=None):
        """Show the History tab content."""
        self.clear_content()
        self.current_tab = 'history'
        self.highlight_current_tab()
        create_history_tab(self)

    def show_connections_tab(self, widget=None):
        """Show the Connections tab content."""
        self.clear_content()
        self.current_tab = 'connections'
        self.highlight_current_tab()
        create_connections_tab(self)

    def show_settings_tab(self, widget=None):
        """Show the Settings tab content."""
        self.clear_content()
        self.current_tab = 'settings'
        self.highlight_current_tab()
        create_settings_tab(self)

def main():
    return Group16()