import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER
import requests
import asyncio
import time


class LoginScreen:
    """Login screen for the app with Remember Me and account creation capability."""

    def __init__(self, app, on_login_success):
        self.app = app
        self.on_login_success = on_login_success

        # Initialize persistent accounts on the app.
        # Always keep the "joey" account with password "123".
        if not hasattr(self.app, 'accounts'):
            self.app.accounts = {"joey": "123"}
        self.valid_credentials = self.app.accounts

        # Login attempt tracking
        if not hasattr(self.app, 'login_attempts'):
            self.app.login_attempts = 0
        self.login_attempts = self.app.login_attempts

        # Lockout tracking
        if not hasattr(self.app, 'lockout_until'):
            self.app.lockout_until = 0
        self.lockout_until = self.app.lockout_until

        # Maximum login attempts before lockout
        self.max_attempts = 5

        # Lockout duration in seconds (10 minutes)
        self.lockout_duration = 600

        # Load stored login info from the app attribute.
        self.stored_login = self.load_remembered_login()

        # Auto-login if stored credentials exist, are valid, and the user did not just log out.
        if (self.stored_login and
                not getattr(self.app, 'just_logged_out', False) and
                self.check_credentials(self.stored_login.get("patient_id", ""),
                                       self.stored_login.get("password", ""))):
            asyncio.create_task(self.auto_login())

        # Setup a timer to check lockout status periodically
        self.lockout_timer = None
        if self.is_locked_out():
            self.start_lockout_timer()

    def build(self):
        """Build the login screen UI."""
        main_box = toga.Box(style=Pack(
            direction=COLUMN,
            margin=20,
            background_color='#F0F0F0',
            align_items=CENTER,
            flex=1
        ))

        # App title
        title_box = toga.Box(style=Pack(
            direction=COLUMN,
            margin=(0, 0, 30, 0),
            align_items=CENTER
        ))
        title_label = toga.Label(
            'Nocturnal',
            style=Pack(font_size=26, font_weight='bold', text_align=CENTER)
        )
        subtitle_label1 = toga.Label(
            'Hypoglycemia',
            style=Pack(font_size=26, font_weight='bold', text_align=CENTER)
        )
        subtitle_label2 = toga.Label(
            'Management App',
            style=Pack(font_size=26, font_weight='bold', text_align=CENTER)
        )
        title_box.add(title_label)
        title_box.add(subtitle_label1)
        title_box.add(subtitle_label2)
        main_box.add(title_box)

        # Login form
        form_box = toga.Box(style=Pack(
            direction=COLUMN,
            margin=(0, 0, 20, 0),
            width=300
        ))

        # Patient ID input
        self.patient_id_input = toga.TextInput(
            placeholder='Patient ID',
            style=Pack(margin=(10, 5), width=300, height=40, font_size=16)
        )
        if self.stored_login:
            self.patient_id_input.value = self.stored_login.get("patient_id", "")
        form_box.add(self.patient_id_input)

        # Spacer between inputs
        form_box.add(toga.Box(style=Pack(height=10)))

        # Password input
        self.password_input = toga.PasswordInput(
            placeholder='Password',
            style=Pack(margin=(10, 5), width=300, height=40, font_size=16)
        )
        if self.stored_login:
            self.password_input.value = self.stored_login.get("password", "")
        form_box.add(self.password_input)

        # Spacer before checkbox
        form_box.add(toga.Box(style=Pack(height=10)))

        # Remember me checkbox
        checkbox_box = toga.Box(style=Pack(direction=ROW, align_items=CENTER))
        self.remember_checkbox = toga.Switch('Remember me', on_change=self.toggle_remember_me)
        if self.stored_login:
            self.remember_checkbox.value = True
        checkbox_box.add(self.remember_checkbox)
        form_box.add(checkbox_box)
        main_box.add(form_box)

        # Buttons container
        buttons_box = toga.Box(style=Pack(direction=COLUMN, width=300, align_items=CENTER))
        self.login_button = toga.Button(
            'Login',
            on_press=self.handle_login,
            style=Pack(margin=12, background_color='#2196F3', color='white', width=300, font_size=16)
        )
        buttons_box.add(self.login_button)
        buttons_box.add(toga.Box(style=Pack(height=10)))
        self.create_account_button = toga.Button(
            'Create New Account',
            on_press=self.handle_create_account,
            style=Pack(margin=12, background_color='#2196F3', color='white', width=300, font_size=16)
        )
        buttons_box.add(self.create_account_button)
        main_box.add(buttons_box)

        # Error message label
        self.error_label = toga.Label(
            '',
            style=Pack(color='#D32F2F', font_size=14, text_align=CENTER, margin_top=10)
        )
        main_box.add(self.error_label)

        # Attempts remaining label
        self.attempts_label = toga.Label(
            '',
            style=Pack(color='#FFA500', font_size=14, text_align=CENTER, margin_top=5)
        )
        main_box.add(self.attempts_label)

        # Lockout label
        self.lockout_label = toga.Label(
            '',
            style=Pack(color='#D32F2F', font_size=14, text_align=CENTER, font_weight='bold', margin_top=5)
        )
        main_box.add(self.lockout_label)

        # Check if we're currently locked out
        if self.is_locked_out():
            self.update_lockout_ui()

        return main_box

    def handle_login(self, widget):
        """Handle login button press."""
        # Check if account is locked out
        if self.is_locked_out():
            self.update_lockout_ui()
            return

        patient_id = self.patient_id_input.value.strip()
        password = self.password_input.value.strip()

        if not patient_id or not password:
            self.error_label.text = 'Please enter Patient ID and Password'
            return

        if self.check_credentials(patient_id, password):
            # Reset login attempts on successful login
            self.login_attempts = 0
            self.app.login_attempts = 0
            self.attempts_label.text = ''

            if self.remember_checkbox.value:
                self.save_login(patient_id, password)
                try:
                    url = "http://127.0.0.1:8000/remember_login"
                    payload = {
                        "username": patient_id,
                        "password": password,
                        "remember": True
                    }
                    response = requests.post(url, json=payload)
                    data = response.json()
                    print("Backend response:", data)
                except Exception as e:
                    print("Error calling backend:", e)
            else:
                self.clear_stored_login()
            self.on_login_success()
        else:
            # Increment login attempts
            self.login_attempts += 1
            self.app.login_attempts = self.login_attempts

            # Check if max attempts reached
            if self.login_attempts >= self.max_attempts:
                self.lock_account()
            else:
                remaining = self.max_attempts - self.login_attempts
                self.error_label.text = 'Invalid Patient ID or Password'
                self.attempts_label.text = f'Login Attempts Remaining: {remaining}'

    def lock_account(self):
        """Lock the account for the specified duration."""
        self.lockout_until = time.time() + self.lockout_duration
        self.app.lockout_until = self.lockout_until
        self.update_lockout_ui()
        self.start_lockout_timer()

    def is_locked_out(self):
        """Check if the account is currently locked out."""
        return time.time() < self.lockout_until

    def update_lockout_ui(self):
        """Update UI to reflect lockout status."""
        if self.is_locked_out():
            # Calculate remaining lockout time
            remaining_seconds = int(self.lockout_until - time.time())
            remaining_minutes = remaining_seconds // 60
            remaining_seconds = remaining_seconds % 60

            self.error_label.text = 'Account is temporarily locked'
            self.attempts_label.text = f'Too many failed login attempts'
            self.lockout_label.text = f'10 Minute Lockout'

            # Disable input fields and buttons
            self.patient_id_input.enabled = False
            self.password_input.enabled = False
            self.login_button.enabled = False
            self.create_account_button.enabled = False
            self.remember_checkbox.enabled = False
        else:
            # Reset UI when lockout is over
            self.lockout_label.text = ''
            self.attempts_label.text = ''
            self.error_label.text = ''

            # Re-enable input fields and buttons
            self.patient_id_input.enabled = True
            self.password_input.enabled = True
            self.login_button.enabled = True
            self.create_account_button.enabled = True
            self.remember_checkbox.enabled = True

            # Reset login attempts
            self.login_attempts = 0
            self.app.login_attempts = 0

    def start_lockout_timer(self):
        """Start a timer to periodically check and update lockout status."""

        async def check_lockout():
            while self.is_locked_out():
                self.update_lockout_ui()
                await asyncio.sleep(1)  # Check every second

            # When lockout expires
            self.update_lockout_ui()
            return

        if self.lockout_timer:
            self.lockout_timer.cancel()

        self.lockout_timer = asyncio.create_task(check_lockout())

    def handle_create_account(self, widget):
        """Open a new window for account creation."""
        # Check if account is locked out
        if self.is_locked_out():
            self.update_lockout_ui()
            return

        self.account_window = toga.Window(title="Create Account", size=(350, 250))
        self.app.windows.add(self.account_window)

        main_box = toga.Box(style=Pack(
            direction=COLUMN,
            margin=20,
            background_color='#f0f0f0',
            align_items=CENTER
        ))
        # Add a border to the account creation box
        main_box.style.border_color = '#444444'
        main_box.style.border_width = 1

        # Patient ID error label and input.
        self.patient_id_error = toga.Label("", style=Pack(color='red'))
        self.new_patient_id_input = toga.TextInput(placeholder="Patient ID", style=Pack(width=250))
        patient_box = toga.Box(style=Pack(direction=COLUMN, margin_bottom=10))
        patient_box.add(self.patient_id_error)
        patient_box.add(self.new_patient_id_input)

        # Password error label and input.
        self.password_error = toga.Label("", style=Pack(color='red'))
        self.new_password_input = toga.TextInput(placeholder="Password", style=Pack(width=250))
        password_box = toga.Box(style=Pack(direction=COLUMN, margin_bottom=10))
        password_box.add(self.password_error)
        password_box.add(self.new_password_input)

        main_box.add(patient_box)
        main_box.add(password_box)

        # Create Account and Cancel buttons.
        create_button = toga.Button(
            "Create Account",
            on_press=self.handle_create_account_submit,
            style=Pack(background_color='#000080', color='white', margin=10, width=120)
        )
        cancel_button = toga.Button(
            "Cancel",
            on_press=lambda w: self.account_window.close(),
            style=Pack(background_color='#D32F2F', color='white', margin=10, width=120)
        )
        button_box = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=10))
        button_box.add(create_button)
        button_box.add(toga.Box(style=Pack(width=20)))  # Spacer.
        button_box.add(cancel_button)
        main_box.add(button_box)

        self.account_window.content = main_box
        self.account_window.show()

    def handle_create_account_submit(self, widget):
        """Handle the submission of the new account creation form."""
        patient_id = self.new_patient_id_input.value.strip()
        password = self.new_password_input.value.strip()
        error = False

        if not patient_id:
            self.patient_id_error.text = "Error: Blank"
            error = True
        else:
            self.patient_id_error.text = ""

        if not password:
            self.password_error.text = "Error: Blank"
            error = True
        else:
            self.password_error.text = ""

        # Do not allow creation of an account with username "joey"
        if patient_id.lower() == "joey":
            self.patient_id_error.text = 'Cannot create account with reserved username "joey"'
            error = True

        # Check if account already exists.
        if patient_id in self.valid_credentials:
            self.patient_id_error.text = 'Account already exists'
            error = True

        # Check if we have reached the maximum of 10 additional accounts.
        additional_accounts = len(self.valid_credentials) - 1  # Exclude "joey"
        if additional_accounts >= 10:
            self.patient_id_error.text = 'Maximum number of additional accounts reached'
            error = True

        if not error:
            # Save the new account into the app's accounts dictionary.
            self.valid_credentials[patient_id] = password
            print(f"New account created: {patient_id} / {password}")
            self.account_window.close()

    def toggle_remember_me(self, widget):
        """Handle the Remember Me toggle."""
        self.remember_me = widget.value

    def check_credentials(self, patient_id, password):
        """Check if credentials are valid."""
        return patient_id in self.valid_credentials and self.valid_credentials[patient_id] == password

    def save_login(self, patient_id, password):
        """Save login credentials locally and in the app attribute."""
        self.stored_login = {"patient_id": patient_id, "password": password}
        self.app.remembered_login = self.stored_login

    def load_remembered_login(self):
        """Load any stored credentials from the app."""
        return getattr(self.app, 'remembered_login', None)

    def clear_stored_login(self):
        """Clear stored credentials if Remember Me is unchecked."""
        self.stored_login = None
        if hasattr(self.app, 'remembered_login'):
            del self.app.remembered_login

    async def auto_login(self, widget=None):
        """Automatically log in using stored credentials if conditions permit."""
        if getattr(self.app, 'just_logged_out', False):
            print("Auto-login skipped due to recent logout.")
            return

        # Don't auto-login if account is locked out
        if self.is_locked_out():
            self.update_lockout_ui()
            return

        self.on_login_success()


# Example startup function for your BeeWare app:
def main():
    def on_login_success():
        print("Login was successful! Proceeding to main screen...")
        # Switch to your main app content here.
        app.main_window.content = toga.Box(style=Pack(direction=COLUMN, align_items=CENTER))
        welcome_label = toga.Label("Welcome to Nocturnal Hypoglycemia Management App", style=Pack(font_size=20))
        app.main_window.content.add(welcome_label)

    login_screen = LoginScreen(app, on_login_success)
    return login_screen.build()


app = toga.App("Nocturnal Hypoglycemia", "org.beeware.nocthypo", startup=main)

if __name__ == '__main__':
    app.main_loop()