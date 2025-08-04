import math
import numpy as np

# Constants
C = 299_792_458  # Speed of light in m/s
FREQ_GPS_L1 = 1575.42e6  # GPS L1 frequency in Hz
EARTH_RADIUS = 6378137.0  # Earth radius in meters (WGS84)
ECCENTRICITY_SQ = 6.69437999014e-3 # Somethign I don't get

# self
def deg2rad(deg):
    return deg * math.pi / 180.0

#self
def latlonalt_to_ecef(lat_deg, lon_deg, alt_m):
    lat = deg2rad(lat_deg)
    lon = deg2rad(lon_deg)
    N = EARTH_RADIUS / math.sqrt(1 - ECCENTRICITY_SQ * (math.sin(lat)**2))
    X = (N + alt_m) * math.cos(lat) * math.cos(lon)
    Y = (N + alt_m) * math.cos(lat) * math.sin(lon)
    Z = (N * (1 - ECCENTRICITY_SQ) + alt_m) * math.sin(lat)
    return (X, Y, Z)

#self
def distance_ecef(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2 + (p1[2] - p2[2])**2)

#self
def angular_velocity(angle1, angle2, delta_t):
    # Handle wrap-around for angles in degrees
    diff = angle2 - angle1
    if diff > 180:
        diff -= 360
    elif diff < -180:
        diff += 360
    return diff / delta_t  # degrees per second

#se;f
def doppler_shift(range1, range2, delta_t, carrier_freq=FREQ_GPS_L1):
    radial_velocity = (range2 - range1) / delta_t  # m/s
    return (radial_velocity / C) * carrier_freq  # Hz

#self
def slant_range(sat_lat, sat_lon, sat_alt, obs_lat, obs_lon, obs_alt):
    sat_xyz = latlonalt_to_ecef(sat_lat, sat_lon, sat_alt)
    obs_xyz = latlonalt_to_ecef(obs_lat, obs_lon, obs_alt)
    return distance_ecef(sat_xyz, obs_xyz)


def unit_vector_components(sat_lat, sat_lon, sat_alt, obs_lat, obs_lon, obs_alt):
    """
    Calculate the unit vector components from observer to satellite in ECEF coordinates.

    Returns: (ux, uy, uz)
    """
    sat_x, sat_y, sat_z = latlonalt_to_ecef(sat_lat, sat_lon, sat_alt)
    obs_x, obs_y, obs_z = latlonalt_to_ecef(obs_lat, obs_lon, obs_alt)

    dx = sat_x - obs_x
    dy = sat_y - obs_y
    dz = sat_z - obs_z

    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    if dist == 0:
        return 0.0, 0.0, 0.0  

    return dx/dist, dy/dist, dz/dist

#self
def is_satellite_visible(sat_elevation):
    return sat_elevation > 0 

def estimate_snr(elevation_deg, frequency_hz, slant_range_m, system_noise_temp_k=290, bandwidth_hz=1e6,
                 satellite_eirp_dbw=50, antenna_gain_dbi=30):
    """
    Estimate SNR in dB-Hz of a satellite signal at given elevation and frequency.

    Parameters:
    - elevation_deg: Satellite elevation angle (degrees)
    - frequency_hz: Signal frequency (Hz)
    - slant_range_m: Distance from observer to satellite in meters
    - system_noise_temp_k: System noise temperature (Kelvin), default 290K
    - bandwidth_hz: Receiver bandwidth (Hz), default 1 MHz
    - satellite_eirp_dbw: Satellite EIRP in dBW, default 50 dBW
    - antenna_gain_dbi: Receiver antenna gain in dBi, default 30 dBi

    Returns:
    - snr_dbHz: Estimated SNR in dB-Hz
    """
    # I don't get this well

    if elevation_deg <= 0:
        return 0.0  # satellite below horizon, no signal

    k = 1.380649e-23

    # Free space path loss (FSPL) in dB, is 20 log10 (\frac{4 \pi d}{wavelength})
    wavelength = C / frequency_hz
    fspl_db = 20 * math.log10(4 * math.pi * slant_range_m / wavelength)

    # Atmospheric loss approximation increasing at low elevation, 2 + (10 - elevation * 0.5)
    atm_loss_db = 2 if elevation_deg > 10 else 2 + (10 - elevation_deg) * 0.5

    # Antenna gain loss factor 
    gain_loss_db = max(0, 10 * math.log10(math.sin(math.radians(elevation_deg))))

    # Received power in dBW
    received_power_dbw = satellite_eirp_dbw + antenna_gain_dbi - fspl_db - atm_loss_db + gain_loss_db

    # Noise power in dBW: N = k * T * B, convert to dBW
    noise_power_watts = k * system_noise_temp_k * bandwidth_hz
    noise_power_dbw = 10 * math.log10(noise_power_watts)

    # SNR in dB
    snr_dbHz = received_power_dbw - noise_power_dbw

    return snr_dbHz

def calculate_metrics(data, observer):
    """
    data: list of dicts with keys:
        - satlatitude (deg)
        - satlongitude (deg)
        - elevation (deg)
        - azimuth (deg)
        - timestamp (int, seconds)
    observer: dict with keys 'lat', 'lon', 'alt' (meters)

    Returns:
        List of dicts with:
            - time_interval (s)
            - angular_velocity_az (deg/s)
            - angular_velocity_el (deg/s)
            - doppler_shift (Hz)
            - slant_range (m)
            - time_delay (s)
            - visible
            - snr (db-Hz)
    """
    results = []

    for i in range(len(data) - 1):
        d1 = data[i]
        d2 = data[i+1]

        dt = d2['timestamp'] - d1['timestamp']
        if dt <= 0:
            continue

        # Angular velocities
        omega_az = angular_velocity(d1['azimuth'], d2['azimuth'], dt)
        omega_el = angular_velocity(d1['elevation'], d2['elevation'], dt)

        # Slant ranges
        range1 = slant_range(d1['satlatitude'], d1['satlongitude'], d1['sataltitude'], observer['lat'], observer['lon'], observer['alt'])
        range2 = slant_range(d2['satlatitude'], d2['satlongitude'], d1['sataltitude'], observer['lat'], observer['lon'], observer['alt'])

        # Doppler shift
        doppler = doppler_shift(range1, range2, dt)

        # Time delay (signal travel time)
        time_delay = range1 / C  # seconds
        
        #visible
        visible = is_satellite_visible(d1['elevation'])

        # SNR (db-Hz), very shoddy estimate
        snr = estimate_snr(d1['elevation'], 1575.42e6, range1) 

        # Unit vector values
        ux, uy, uz = unit_vector_components(d1['satlatitude'], d1['satlongitude'], d1['sataltitude'], observer['lat'], observer['lon'], observer['alt'])


        results.append({
            'time_interval': dt,
            'angular_velocity_az': omega_az,
            'angular_velocity_el': omega_el,
            'doppler_shift_hz': doppler,
            'slant_range_m': range1,
            'time_delay_s': time_delay,
            'timestamp': d1['timestamp'],
            'visible': visible,
            'snr': snr,
            'unit_vector': (ux, uy, uz)
        })

    return results

# Perhaps
def calculate_dop(sat_positions_ecef, receiver_ecef):
    """
    Calculate DOP values given satellite and receiver positions in ECEF coordinates.

    Parameters:
    - sat_positions_ecef: list or array of shape (n,3) of satellite ECEF positions [meters]
    - receiver_ecef: array of shape (3,) of receiver ECEF position [meters]

    Returns:
    - dict with keys: GDOP, PDOP, HDOP, VDOP, TDOP
    """

    n = len(sat_positions_ecef)
    if n < 4:
        raise ValueError("At least 4 satellites required for DOP calculation")

    G = np.zeros((n, 4))

    for i, sat_pos in enumerate(sat_positions_ecef):
        diff = sat_pos - receiver_ecef
        r = np.linalg.norm(diff)
        if r == 0:
            raise ValueError("Satellite position coincides with receiver position")

        # Line-of-sight unit vector components
        ux, uy, uz = diff / r

        # Geometry matrix row: [ux, uy, uz, 1]
        G[i, 0] = ux
        G[i, 1] = uy
        G[i, 2] = uz
        G[i, 3] = 1.0

    try:
        Q = np.linalg.inv(G.T @ G)
    except np.linalg.LinAlgError:
        raise ValueError("Geometry matrix singular, DOP undefined")

    GDOP = np.sqrt(np.sum(np.diag(Q)))
    PDOP = np.sqrt(Q[0, 0] + Q[1, 1] + Q[2, 2])
    HDOP = np.sqrt(Q[0, 0] + Q[1, 1])
    VDOP = np.sqrt(Q[2, 2])
    TDOP = np.sqrt(Q[3, 3])

    return {"GDOP": GDOP, "PDOP": PDOP, "HDOP": HDOP, "VDOP": VDOP, "TDOP": TDOP}

