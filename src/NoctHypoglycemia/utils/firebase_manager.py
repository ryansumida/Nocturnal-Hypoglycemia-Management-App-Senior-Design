import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime
import uuid
import os
import pathlib


class FirebaseManager:
    def __init__(self):
        self.app = None
        self.db = None
        self.current_session_id = None

    def initialize(self):
        """Initialize Firebase connection"""
        if not firebase_admin._apps:
            # Get the path to the keys directory
            app_path = pathlib.Path(__file__).parent
            keys_path = os.path.join(app_path, 'keys')
            firebase_key_path = os.path.join(keys_path, 'firebase-key.json')

            # Check if the key file exists
            if os.path.exists(firebase_key_path):
                cred = credentials.Certificate(firebase_key_path)
                self.app = firebase_admin.initialize_app(cred)
                self.db = firestore.client()
                print("Firebase initialized with service account")
                return True
            else:
                print(f"Warning: Firebase key file not found at {firebase_key_path}")
                return False
        else:
            self.db = firestore.client()
            return True

    def start_new_session(self, device_type):
        """Start a new monitoring session"""
        if not self.db:
            print("Firebase not initialized")
            return None

        self.current_session_id = str(uuid.uuid4())

        # Create new session document with server timestamp
        session_data = {
            'start_time': firestore.SERVER_TIMESTAMP,
            'device_type': device_type,
            'readings': []
        }

        # Save to Firestore
        self.db.collection('glucose_sessions').document(self.current_session_id).set(session_data)
        print(f"Started new {device_type} session: {self.current_session_id}")
        return self.current_session_id

    def save_reading(self, time, glucose, prediction, state, protocol_activated=False):
        """Save a glucose reading to the current session"""
        if not self.db or not self.current_session_id:
            print("Firebase not initialized or no session started")
            return False

        # Convert time to a Firestore timestamp
        # Note: We're not using SERVER_TIMESTAMP here because we want to preserve the actual reading time
        # Instead, we use the existing datetime object directly, as Firestore can handle Python datetime objects

        reading = {
            'time': time,  # Firestore automatically converts Python datetime to Firestore timestamp
            'glucose': int(glucose) if glucose is not None else None,
            'prediction': int(prediction) if prediction is not None else None,
            'state': state,
            'protocol_activated': protocol_activated
        }

        try:
            # Get the session document
            session_ref = self.db.collection('glucose_sessions').document(self.current_session_id)

            # Update the readings array with a new reading
            session_ref.update({
                'readings': firestore.ArrayUnion([reading])
            })

            print(f"Saved reading: Glucose={glucose}, State={state}")
            return True
        except Exception as e:
            print(f"Error saving reading: {e}")
            import traceback
            traceback.print_exc()  # More detailed error information
            return False

    def get_recent_sessions(self, limit=10):
        """Get recent sessions, limited to the last 10 by default"""
        if not self.db:
            print("Firebase not initialized")
            return []

        try:
            sessions = self.db.collection('glucose_sessions') \
                .order_by('start_time', direction=firestore.Query.DESCENDING) \
                .limit(limit) \
                .get()

            result = []
            for session in sessions:
                session_data = session.to_dict()
                reading_count = len(session_data.get('readings', []))
                print(f"Retrieved session: {session.id} with {reading_count} readings")
                result.append(session_data)

            return result
        except Exception as e:
            print(f"Error getting sessions: {e}")
            import traceback
            traceback.print_exc()
            return []


# Create a singleton instance
firebase_manager = FirebaseManager()