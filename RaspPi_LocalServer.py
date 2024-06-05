from flask import Flask, request, jsonify
import threading
import collections
import time
import firebase_admin
from firebase_admin import credentials, firestore
import numpy as np
from scipy.signal import find_peaks
import json
import os


# Flask setup
app = Flask(__name__)

# Path to Firebase Admin SDK private Key
cred = credentials.Certificate("ecgapp-7d874-firebase-adminsdk-obhri-ee5abe4640.json")
firebase_admin.initialize_app(cred)

# Get a Firestore Client
db = firestore.client()


# Local table for deviceId to userId mapping
device_user_table = {}

# Initialize a lock, returns an instance of the Lock class
device_user_table_lock = threading.Lock();
file_lock = threading.Lock();

ERROR_FILE = "local_storage_errors.json"

def write_to_error_file(error_message, eq_id, initial_timestamp, ecg_values):
    # Write in a local file the data that is not transmitted to cloud due to an error
    
    json_entry= {
        "error_message": error_message,
        "initial_timestamp": initial_timestamp,
        "eq_id": eq_id,
        "ecg_values" : ecg_values
    }
    
    # Use lock to write safely
    with file_lock:
        # Open file in append mode
        file = open(ERROR_FILE, "a")
        try:
            file.write(json.dumps(json_entry) + "\n") # Write to file
        finally:
            file.close() # Close the file
    
        
def update_device_user_table():
    # Update the local table with deviceId to userId mappings from Firestore.
    
    # Reference to UserAuthList collection
    users_ref = db.collection("UserAuthList")
    # Get all documents in the collection
    docs = users_ref.stream()
    
    #Modify the global variable device_user_table
    global device_user_table
    new_table = {doc.to_dict().get("DeviceId"): doc.id for doc in docs} # Create new mapping table deviceId : userId
    
    # Use the lock so that the table update is thread-safe
    with device_user_table_lock:
        device_user_table = new_table # Assign new table to global table
    
def get_user_id_by_device_id(device_id):
    # Retrieve userId from the local cache using deviceId. Update cache if necessary.

    if device_id not in device_user_table:
        # Update the cache if deviceId is not found, indicating a potential new registration
        update_device_user_table()

    return device_user_table.get(device_id) # Return userId or None
    
    
def generate_dictionary_ecg_value_timestamp(initial_timestamp, ecg_values, sampling_interval):
    # Generate dictionary of ECG values with their coresponding times, the sampling interval is 10 ms, so ecgValue1 will have initial_timestamp, ecg_value2 - initial_timestamp+10, ecg_value3 - initial timestamp + 20 
    
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
    # Upload ecg data and computed health parameters to Firestore

    # Use cache to get userId
    user_id = get_user_id_by_device_id(eq_id)

    if not user_id:
        error_message = f"Eq id {eq_id} is not recogognized!"
        print(error_message)
        write_to_error_file(error_message, initial_timestamp, eq_id, ecg_values)
    elif -1 in ecg_values:
        error_message = "Lead off detected! Data will not be forwarded to cloud"
        print(error_message)
        write_to_error_file(error_message, initial_timestamp, eq_id, ecg_values)
    else:

        # Construct dictionary ecg_value , timestamp
        ecg_data = generate_dictionary_ecg_value_timestamp(initial_timestamp, ecg_values, sampling_interval=10)
        
        # Get health parameters
        rr_intervals, bpm, sdnn, rmssd = compute_health_parameters(ecg_values)

        # Firestore data upload
        try:
            doc_ref = db.collection("ecg_data").document(user_id).collection("readings").document(initial_timestamp)
            doc_ref.set({
            "ecg_data": ecg_data,
            "rr_intervals": rr_intervals.tolist(),
            "bpm": bpm,
            "sdnn": sdnn,
            "rmssd": rmssd
            })
            print("Data uploaded successfully.")
        except Exception as e:
            error_message = f"Failed to upload data: {e}"
            print(error_message)
            write_to_error_file(error_message, initial_timestamp, eq_id, ecg_values)
            
    

@app.route('/post-data', methods=['POST'])
def post_data():
    # Handle post request to receive and process ECG data

    try:
        data = request.json #Get json data from request
        #Extract parameters
        initial_timestamp = data.get("initialTimestamp")  
        eq_id = data.get("eqID") 
        ecg_values = data.get("ecgValues", [])
        
        # upload data to firestore
        upload_data(initial_timestamp,eq_id,ecg_values)

        return jsonify({"message": "Data received successfully"}), 200 # Return success code
    except Exception as e:
        error_message = f"Error processing request: {e}"
        print(error_message)
        write_to_error_file(error_message, None, None, None)
        return jsonify({"error": "Server error"}), 500 #Return error

        
# Background thread for periodic cache updates
def start_table_update_thread(interval=3600 * 24): # update once a day
    #Start a background thread that updates the cache 
    
    def update():
        while True: # Infinite loop
            update_device_user_table() # Update table
            time.sleep(interval) # Wait for interval
    
    thread = threading.Thread(target=update) # Create a background thread to run the update functionality
    thread.daemon = True  # Daemon threads as daemon, stops at the end of the program
    thread.start() # Start the thread

if __name__ == "__main__":
    # Initial update of the device id
    update_device_user_table()
    # Start the periodic update thread
    start_table_update_thread()
    app.run(host="0.0.0.0", port=5000, debug=True) # Run the flask app on all available IP adresses on port 5000

