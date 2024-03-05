from flask import Flask, request, jsonify
import matplotlib.pyplot as plt
import threading
import collections
import time
import logging

# Flask setup
app = Flask(__name__)

# Circular buffer for EKG data
ekg_data_buffer = collections.deque(maxlen=1000)

# Flask route to receive data
@app.route('/post-data', methods=['POST'])
def post_data():
    try:
        data = request.json
        startReadingTime=data.get('startReadingTime')
        eqID=data.get('eqID')
        ekg_data = data.get('ekgData', [])
        for value in ekg_data:
            ekg_data_buffer.append(value)  # Append new data to the buffer
        print(f"time= {startReadingTime} eqID={eqID}")
        return jsonify({"message": "Data received successfully"}), 200
    except Exception as e:
        logging.exception(e)
        print(request.data)
        raise e

# Function to run the Flask app in a separate thread
def run_flask_app():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    

# Initialize the plot
plt.ion()  # Turn on interactive mode
fig, ax = plt.subplots()
line, = ax.plot([], [], lw=2)
ax.set_title("Real-Time EKG Data")
ax.set_xlabel("Samples")
ax.set_ylabel("Reading")
ax.grid(True)

# Function to update the plot
def update_plot():
    while True:
        if ekg_data_buffer:
            line.set_data(range(len(ekg_data_buffer)), list(ekg_data_buffer))
            ax.relim()
            ax.autoscale_view(True, True, True)
            fig.canvas.draw()
            fig.canvas.flush_events()
        time.sleep(0.5)  # Update interval

# Start the Flask server in a separate thread
flask_thread = threading.Thread(target=run_flask_app)
flask_thread.daemon = True
flask_thread.start()

# Update plot in the main thread
update_plot()