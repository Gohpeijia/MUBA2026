import os
import firebase_admin
from firebase_admin import credentials, firestore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_PATH = os.path.join(BASE_DIR, 'firebase-adminsdk.json')

def init_firebase():
    # This check prevents Flask from crashing by trying to initialize twice when reloading
    if not firebase_admin._apps:
        cred = credentials.Certificate(CRED_PATH)
        firebase_admin.initialize_app(cred)
    return firestore.client()

# Export the db instance
db = init_firebase()