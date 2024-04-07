from flask import Flask, request, jsonify
import threading
import collections
import time
import logging
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta


# Flask setup
app = Flask(__name__)

# Path to Firebase Admin SDK private Key
cred = credentials.Certificate('ecgapp-7d874-firebase-adminsdk-obhri-ee5abe4640.json')
firebase_admin.initialize_app(cred)

# Get a Firestore Client
db = firestore.client()


# Local table for deviceId to userId mapping
device_user_table = {}

def update_device_user_table():
    #Update the local table with deviceId to userId mappings from Firestore.
    
    users_ref = db.collection('UserAuthList')
    docs = users_ref.stream()
    
    global device_user_table
    new_table = {doc.to_dict().get('DeviceId'): doc.id for doc in docs}
    device_user_table = new_table
    
def get_user_id_by_device_id(device_id):
    #Retrieve userId from the local cache using deviceId. Update cache if necessary.
    
    if device_id not in device_user_table:
        # Update the cache if deviceId is not found, indicating a potential new registration
        update_device_user_table()
    print("Current Device-User Mapping:")
    for device, user in device_user_table.items():
        print(f"Device ID: {device} -> User ID: {user}")
    return device_user_table.get(device_id)
    
    
def convert_elapsed_time_to_exact_time(initial_timestamp, elapsed_time_values):
    #Convert initial timestamp to a datetime object
    initial_timestamp = datetime.strptime(initial_timestamp, '%Y-%m-%d %H:%M:%S')
    
    #Initialize array for exact time values
    time_values = []
    
    for value in elapsed_time_values:
        #Compute the time by adding ellapsed milliseconds to the initial time
        reading_time = initial_timestamp + timedelta(milliseconds=value)
        time_values.append(reading_time)
        
    return time_values
    

@app.route('/post-data', methods=['POST'])
def post_data():
    try:
        data = request.json
        initial_timestamp = data.get('initialTimestamp')  
        eq_id = data.get('eqID')
        ecg_values = data.get('ecgValues', [])
        elapsed_time_values = data.get('elapsedTimeValues',[])

        # Use cache to get userId
        user_id = get_user_id_by_device_id(eq_id)
        
        if not user_id:
            return jsonify({"message": "Device ID not associated with any user"}), 400

        # Convert string timestamp to datetime object and calculate real timestamps
        real_timestamps = convert_elapsed_time_to_exact_time(initial_timestamp, elapsed_time_values)
        
        # Convert initial time to document format for Firestore document name
        document_timestamp = datetime.strptime(initial_timestamp, '%Y-%m-%d %H:%M:%S').strftime('%Y%m%d%H%M%S')
        readings_data = [{'ecgValue': ecg_value, 'real_timestamp': timestamp.strftime('%H:%M:%S.%f')[:-3]} for ecg_value, timestamp in zip(ecg_values, real_timestamps)]

        # Firestore data upload
        doc_ref = db.collection('ecg_data').document(user_id).collection('readings').document(document_timestamp)
        doc_ref.set({'readings': readings_data})
        
        return jsonify({"message": "Data received successfully"}), 200
    except Exception as e:
        logging.exception("Error: %s", e)
        return jsonify({"error": "Server error"}), 500

        
# Background thread for periodic cache updates
def start_table_update_thread(interval=3600 * 60 *2):
    #Start a background thread that updates the cache 
    def update():
        while True:
            update_device_user_table()
            time.sleep(interval)
    
    thread = threading.Thread(target=update)
    thread.daemon = True  # Daemon threads are abruptly stopped at program termination.
    thread.start()

if __name__ == '__main__':
    # Initial cache update
    update_device_user_table()
    # Start the periodic cache update thread
    start_table_update_thread()
    app.run(host='0.0.0.0', port=5000, debug=True)