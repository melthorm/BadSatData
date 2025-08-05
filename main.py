import requests
import json
import time
import curses
import datetime
import os
import sys
import argparse
import threading
import matplotlib.pyplot as plt 
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
from collections import deque

import calculations

# Sets outputs to logs file
def set_output_log():
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"log_{timestamp}.txt")
    sys.stdout = open(log_file, "w")
    sys.stderr = sys.stdout

# Parses arguments
def parse_args():
    parser = argparse.ArgumentParser(description="Really Bad Satellite Tracker")

    parser.add_argument("--api_key", type=str, required=True, help="API key for authentication")
    parser.add_argument("--lat", type=float, default=40.0, help="Observer latitude in degrees")
    parser.add_argument("--lon", type=float, default=-74.0, help="Observer longitude in degrees")
    parser.add_argument("--alt", type=float, default=0.0, help="Observer altitude in meters")
    parser.add_argument("--seconds", type=int, default=300, help="Seconds of data per fetch")
    parser.add_argument("--sat-ids", type=int, nargs="+", default=[
        25544, 20580, 25994, 27424,  # ISS, HST, TERRA, AQUA
        62339, 28474, 40294, 43873, 35752, 39741, 32711, 40730, 40105, 41019,
        48859, 29601, 24876, 46826, 32260, 27663, 28874, 44506, 28190, 26360,
        64202, 26407, 45854, 38833, 36585, 40534, 39166, 55268, 32384, 39533,
        29486, 41328
    ], help="List of satellite NORAD IDs")

    parser.add_argument("--show", nargs="+", choices=[
        "visible", "angular_velocity_az", "angular_velocity_el", "doppler_shift_hz",
        "slant_range_m", "time_delay_s", "snr", "unit_vector", "timestamp"
    ], default=[
        "visible", "angular_velocity_az", "angular_velocity_el", "doppler_shift_hz",
        "slant_range_m", "time_delay_s", "snr", "unit_vector", "timestamp"
    ], help="Which metrics to display")
    parser.add_argument("--plot", action = "store_true", help = "Enable plot that refreshes every 300 s")
    parser.add_argument("--store", action = "store_true", help = "Store data")
    args = parser.parse_args()
    return args


args = parse_args()

API_KEY = args.api_key
LAT = args.lat
LON = args.lon
ALT = args.alt
SECONDS = args.seconds
SAT_IDS = args.sat_ids

observer_pos = {'lat': LAT, 'lon': LON, 'alt': ALT}

# Globals (good technique)
satellites = {}
requestsLastHour = 0
timeToFetchTotal = 0
timeToProcessTotal = 0
lock = threading.Lock()

# Fetches from n2yo api and processes doing stuffs
def fetch_and_process(sat_id):
    url = f"https://api.n2yo.com/rest/v1/satellite/positions/{sat_id}/{LAT}/{LON}/{ALT}/{SECONDS}/&apiKey={API_KEY}"
    try:
        timeToFetch = time.time()
        r = requests.get(url)
        timeToFetch = time.time() - timeToFetch

        if r.status_code == 200:
            data = r.json()
            sat_info = data['info']
            sat_positions = data['positions']
            name = f"{sat_info['satname']} ({sat_info['satid']})"
            requestsLastHour = sat_info['transactionscount']

            timeToProcess = time.time()
            sat_processed = calculations.calculate_metrics(sat_positions, observer_pos)
            timeToProcess = time.time() - timeToProcess

            return name, sat_processed, requestsLastHour, timeToFetch, timeToProcess
    except Exception as e:
        print(f"Exception: {e}")
    return None, None, None, None, None

# Updates in background so it keeps up real time and avoids the problem of 299s
def background_updater():
    global satellites, requestsLastHour, timeToFetchTotal, timeToProcessTotal
    while True:
        cycle_start = time.time()
        for sat_id in SAT_IDS:
            name, metrics, reqs, timeToFetch, timeToProcess = fetch_and_process(sat_id)
            if name and metrics and timeToFetch and timeToProcess:
                with lock:
                    satellites[name] = deque(metrics, maxlen=SECONDS)
                    requestsLastHour = reqs
                    timeToFetchTotal += timeToFetch
                    timeToProcessTotal += timeToProcess
        elapsed = time.time() - cycle_start
        sleep_duration = max(0, SECONDS - elapsed)
        # -1 since calculations rely on two points (one in future)
        time.sleep(sleep_duration-1)

# data
def data_writer_thread():
    os.makedirs("data", exist_ok=True)
    while True:
        time.sleep(SECONDS-1)
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join("data", f"sat_data_{timestamp}.json")

        with lock:
            sats_copy = {k: list(v) for k, v in satellites.items()}

        with open(filename, "w") as f:
            json.dump(sats_copy, f, indent=2, default=str)

def plotting_updater():
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    try:
        mng = plt.get_current_fig_manager()
        mng.full_screen_toggle()
    except:
        try:
            mng.window.state('zoomed')
        except:
            pass
    ax.set_xlim(-7000000, 7000000)
    ax.set_ylim(-7000000, 7000000)
    ax.set_zlim(-7000000, 7000000)
    ax.set_xlabel('X (m)')
    ax.set_ylabel('Y (m)')
    ax.set_zlabel('Z (m)')
    ax.set_title('Real-Time Satellite Positions Around Earth', fontsize=14, pad=20)

    scatters = {}
    observer_x, observer_y, observer_z = calculations.latlonalt_to_ecef(observer_pos['lat'], observer_pos['lon'], observer_pos['alt'])

    # Earth sphere
    u, v = np.mgrid[0:2*np.pi:40j, 0:np.pi:20j]
    earth_x = 6371000 * np.cos(u) * np.sin(v)
    earth_y = 6371000 * np.sin(u) * np.sin(v)
    earth_z = 6371000 * np.cos(v)

    def update(frame):
        ax.clear()
        ax.set_xlim(-7000000, 7000000)
        ax.set_ylim(-7000000, 7000000)
        ax.set_zlim(-7000000, 7000000)
        ax.set_xlabel('X (m)')
        ax.set_ylabel('Y (m)')
        ax.set_zlabel('Z (m)')
        ax.set_title('Real-Time Satellite Positions Around Earth', fontsize=14, pad=20)
        
        ax.plot(observer_x, observer_y, observer_z, 's', color='black', label='Observer')

        ax.plot_surface(earth_x, earth_y, earth_z, color='blue', alpha=0.3, edgecolor='none')
        with lock:
            sats_copy = dict(satellites)
            for name, metrics in sats_copy.items():
                if metrics:
                    m = metrics[0]
                    ecef = m['ecef']
                    x, y, z = ecef[0], ecef[1], ecef[2]
                    ax.plot([x],[y],[z],'o', label = name)
            
        ax.legend(loc='center left', bbox_to_anchor=(1.05, 0.5), fontsize='small', borderaxespad=0.)
        fig.subplots_adjust(right=0.75)

    ani = FuncAnimation(fig, update, interval=1000)
    plt.show()


# Displays table using the coolest thing curses
def display_table_threaded(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_WHITE, -1)

    # Dict to decide what show
    labels_all = {
        "visible": "Visible",
        "angular_velocity_az": "Az vel",
        "angular_velocity_el": "El vel",
        "doppler_shift_hz": "Doppler",
        "slant_range_m": "Range",
        "time_delay_s": "Delay",
        "snr": "SNR",
        "unit_vector": "VectorTo",
        "timestamp": "Timestamp"
    }

    labels = [labels_all[key] for key in args.show]

    column_width = 15 # Column width for all thing other than satellite
    y_offset = 5 # Offset from why since some hader stuff
    t = 0 # Global counter

    pad_pos_y = 0
    pad_pos_x = 0

    stdscr.nodelay(True)
    stdscr.timeout(10)
    last_update_time = time.time()

    while True:
        key = stdscr.getch()
        if key == curses.KEY_DOWN:
            pad_pos_y += 1
        elif key == curses.KEY_UP:
            pad_pos_y = max(pad_pos_y - 1, 0)
        elif key == curses.KEY_RIGHT:
            pad_pos_x += 2
        elif key == curses.KEY_LEFT:
            pad_pos_x = max(pad_pos_x - 2, 0)

        if time.time() - last_update_time >= 1.0:
            with lock:
                sats_copy = dict(satellites)
                reqs = requestsLastHour
                fetch_time = timeToFetchTotal
                process_time = timeToProcessTotal

            name_width = max((len(name) for name in sats_copy), default=10) + 2
            max_rows = len(sats_copy) + y_offset + 2
            pad_height = max_rows
            pad_width = name_width + len(labels) * column_width + 5
            pad = curses.newpad(pad_height, pad_width)

            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pad.addstr(0, 0, f"Satellite Tracker | {current_time}", curses.A_BOLD)
            pad.addstr(1, 0, f"Requests Last Hour (Max: 1000): {reqs} | Iterations: {t}", curses.A_BOLD)
            pad.addstr(2, 0, f"Net Time to Fetch: {fetch_time:.2f} s | Net Time to Process: {process_time:.2f} s", curses.A_BOLD)
            pad.addstr(3, 0, f"Press Ctrl + C to exit", curses.A_BOLD)
            pad.addstr(y_offset, 0, f"{'Satellite':^{name_width-1}}", curses.color_pair(1))
            for col, label in enumerate(labels):
                pad.addstr(y_offset, name_width + col * column_width, f"{label:^{column_width-1}}", curses.color_pair(1))

            for row_offset, (name, metrics) in enumerate(sats_copy.items()):
                row = row_offset + y_offset + 1
                pad.addstr(row, 0, name.ljust(name_width), curses.color_pair(2))
                if metrics:
                    m = metrics[t % len(metrics)]
                    dt = datetime.datetime.fromtimestamp(m['timestamp'])
                    formatted_time = dt.strftime('%H:%M:%S')
                    metric_values = {
                        "visible": f"{m['visible']}",
                        "angular_velocity_az": f"{m['angular_velocity_az']:.2f} °/s",
                        "angular_velocity_el": f"{m['angular_velocity_el']:.2f} °/s",
                        "doppler_shift_hz": f"{m['doppler_shift_hz']:.0f} Hz",
                        "slant_range_m": f"{m['slant_range_m']:.0f} m",
                        "time_delay_s": f"{m['time_delay_s']:.6f} s",
                        "snr": f"{m['snr']:.0f} db-Hz",
                        "unit_vector": f"{m['unit_vector'][0]:.1f}|{m['unit_vector'][1]:.1f}|{m['unit_vector'][2]:.1f}",
                        "timestamp": formatted_time
                    }
                    for col, key in enumerate(args.show):
                        val = metric_values[key]
                        pad.addstr(row, name_width + col * column_width, f"{val:>{column_width-1}}", curses.color_pair(2))


            max_y, max_x = stdscr.getmaxyx()
            pad.refresh(pad_pos_y, pad_pos_x, 0, 0, max_y - 1, max_x - 1)

            last_update_time = time.time()
            t += 1

def main():
    set_output_log()
    background_thread = threading.Thread(target=background_updater, daemon=True)
    background_thread.start()
    if args.plot:
        plotting_thread = threading.Thread(target=plotting_updater, daemon = True)
        plotting_thread.start()
    if args.store:
        storing_thread = threading.Thread(target=data_writer_thread, daemon=True)
        storing_thread.start()
    curses.wrapper(display_table_threaded)

if __name__ == "__main__":
    main()

