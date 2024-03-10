from flask import Flask, request, jsonify
import matplotlib.pyplot as plt
import threading
import collections
import time
import logging
import firebase_admin
from firebase_admin import credentials, firestore

# Path to Firebase Admin SDK private Key
cred = credentials.Certificate('ecgapp-7d874-firebase-adminsdk-obhri-ee5abe4640.json')
firebase_admin.initialize_app(cred)

# Get a Firestore Client
db = firestore.client()

# Flask setup
app = Flask(__name__)


# Flask route to receive data
@app.route('/post-data', methods=['POST'])
def post_data():
    try:
        data = request.json
        timestamp=data.get('startReadingTime')
        eq_id=data.get('eqID')
        ekg_data = data.get('ekgData', [])
        
        #Add data to Firestore
        readings_ref=db.collection('ecg_data').document(eq_id).collection('readings').document()
        readings_ref.set({
            'timestamp': timestamp,
            'ekgData': ekg_data
            })
        
        print(f"time= {timestamp} eqID={eq_id}")
        return jsonify({"message": "Data received successfully"}), 200
    except Exception as e:
        logging.exception(e)
        print(request.data)
        raise e

# Function to run the Flask app in a separate thread
if __name__=='__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)