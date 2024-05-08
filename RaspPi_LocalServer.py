from flask import Flask, request, jsonify
import threading
import collections
import time
import logging
import firebase_admin
from firebase_admin import credentials, firestore
import numpy as np
from scipy.signal import find_peaks


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
    # Update the local table with deviceId to userId mappings from Firestore.
    
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

    return device_user_table.get(device_id)
    
    
def generate_dictionary_ecg_value_timestamp(initial_timestamp, ecg_values, sampling_interval):
    
    # Initialize dictionary of the form {ecg_value, timestamp}
    ecg_data = [ {"ecg_value": value, "timestamp": int(initial_timestamp) + i* sampling_interval} for i,value in enumerate(ecg_values)]
        
    return ecg_data
    
def compute_health_parameters(ecg_values):
    # Detect R peaks
    # The minimum distance for the peak computation is 50 values, which means once every 50 * 10 ms = 500 ms 
    peaks, _ = find_peaks(ecg_values, height=None, distance = 50)
    
    # Compute RR intervals in ms (multiply by 10)
    rr_intervals = np.diff(peaks) * 10
    
    #Compute the average value of rr intervals in ms
    average_rr_interval = np.mean(rr_intervals)
    
    # Compute BPM
    bpm = int (60000/average_rr_interval)
    
    # Compute SDNN (standard deviation of RR intervals)
    sdnn = np.std(rr_intervals)
    
    # Compute RMSSD (root mean square of successive fifferences between consecutive heartbeats)
    # Square the differences between peaks
    squared_diffs = rr_intervals
    
    # Compute the mean
    mean_squared_diffs = np.mean(squared_diffs)
    
    # Compute square root of the mean
    rmssd = np.sqrt(mean_squared_diffs)
    
    return rr_intervals,bpm,sdnn,rmssd
    
    
def upload_data(initial_timestamp,eq_id,ecg_values):
    # Use cache to get userId
    user_id = get_user_id_by_device_id(eq_id)
        
    if not user_id:
        print(f"Eq id {eq_id} is not recogognized!")
    else:

        # Construct dictionary ecg_value , timestamp
        ecg_data = generate_dictionary_ecg_value_timestamp(initial_timestamp, ecg_values, sampling_interval=10)
        
        # Get health parameters
        rr_intervals, bpm, sdnn, rmssd = compute_health_parameters(ecg_values)


        # Firestore data upload
        try:
            doc_ref = db.collection('ecg_data').document(user_id).collection('readings').document(initial_timestamp)
            doc_ref.set({
            "ecg_data": ecg_data,
            "rr_intervals": rr_intervals.tolist(),
            "bpm": bpm,
            "sdnn": sdnn,
            "rmssd": rmssd
            })
            print("Data uploaded successfully.")
        except Exception as e:
            print(f"Failed to upload data: {e}")
            
    

@app.route('/post-data', methods=['POST'])
def post_data():
    try:
        data = request.json
        initial_timestamp = data.get('initialTimestamp')  
        eq_id = data.get('eqID')
        ecg_values = data.get('ecgValues', [])
        
        upload_data(initial_timestamp,eq_id,ecg_values)
        
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