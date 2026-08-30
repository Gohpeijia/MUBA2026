import firebase_admin
from firebase_admin import credentials, firestore

def init_firebase():
    # This check prevents Flask from crashing by trying to initialize twice when reloading
    if not firebase_admin._apps:
        cred = credentials.Certificate('firebase-adminsdk.json')
        firebase_admin.initialize_app(cred)
    return firestore.client()

# Export the db instance
db = init_firebase()