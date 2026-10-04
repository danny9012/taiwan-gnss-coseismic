"""
ngl_timeseries.py

Reusable functions for loading, converting, and plotting Nevada Geodetic
Laboratory (NGL) GNSS station tenv3 time series data, used across the
Meinong (south), Hualien (east), and Tatun (north) earthquake case studies
in this GNSS crustal-deformation project.

Data source: NGL 24-hour final solution tenv3 files
    https://geodesy.unr.edu/NGLStationPages/gpsnetmap/GPSNetMap.html
    (per-station .sta pages link to the downloadable tenv3 ascii files)

tenv3 column layout (whitespace-separated, one row per day):
    site YYMMMDD yyyy.yyyy MJD week d reflon e0(m) east(m) n0(m) north(m)
    u0(m) up(m) ant(m) sig_e sig_n sig_u corr_en corr_eu corr_nu lat lon height

Only columns 0 (site), 1 (date), 8 (east), 10 (north), 12 (up) are used here.
"""

from datetime import datetime
import numpy as np


def load_tenv3(fname):
    """
    Load a (pre-filtered) tenv3 text file for a single station into
    parallel lists of datetimes and east/north/up values (meters,
    relative to NGL's internal reference offset -- NOT yet a displacement).

    Parameters
    ----------
    fname : str
        Path to a text file containing tenv3 rows for one station,
        e.g. produced by grepping the full multi-station download for
        a specific site code and date range (see filter_station_window).

    Returns
    -------
    dates : list[datetime]
    east, north, up : list[float]  (meters)
    """
    dates, east, north, up = [], [], [], []
    with open(fname) as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0] == "site":
                continue
            dt = datetime.strptime(parts[1], "%y%b%d")
            dates.append(dt)
            east.append(float(parts[8]))
            north.append(float(parts[10]))
            up.append(float(parts[12]))
    return dates, east, north, up


def filter_station_window(full_file, station_code, date_prefixes, out_file):
    """
    Extract rows for one station code, matching any of the given
    YYMMMDD-style date prefixes (as used in tenv3 files, e.g. '16FEB0'
    would match 16FEB01..16FEB09), from a larger downloaded tenv3 file,
    and write them to out_file.

    This mirrors the `grep -E "^{station} ({prefixes})"` pattern used
    throughout this project to slice out a quake window from a full
    per-station download.

    Parameters
    ----------
    full_file : str
        Path to the full tenv3 download for one station (as downloaded
        from NGL's per-station page).
    station_code : str
        NGL's station code (may differ from the GDMS/GNSS_IES code --
        see STATION_CODE_MAP below).
    date_prefixes : list[str]
        Regex alternatives matching the YYMMMDD date field, e.g.
        ["16JAN3[01]", "16FEB0[1-7]"] for Jan 30-31 + Feb 1-7.
    out_file : str
        Path to write the filtered rows to.
    """
    import re
    pattern = re.compile(rf"^{station_code} (?:{'|'.join(date_prefixes)})")
    with open(full_file) as fin, open(out_file, "w") as fout:
        for line in fin:
            if pattern.match(line):
                fout.write(line)


def to_relative_mm(east, north, up, reference_index=0):
    """
    Convert absolute east/north/up (meters) into displacement (mm)
    relative to one reference epoch (default: the first row in the window).

    Returns
    -------
    east_mm, north_mm, up_mm : list[float]
    """
    e0, n0, u0 = east[reference_index], north[reference_index], up[reference_index]
    east_mm = [(v - e0) * 1000 for v in east]
    north_mm = [(v - n0) * 1000 for v in north]
    up_mm = [(v - u0) * 1000 for v in up]
    return east_mm, north_mm, up_mm


def pre_post_displacement(east_mm, north_mm, up_mm, n_pre_days):
    """
    Compute displacement from the average of the first n_pre_days
    (assumed pre-quake) to the last day in the window (assumed
    post-quake or quake-day).

    Returns
    -------
    numpy.ndarray of shape (3,): [dEast, dNorth, dUp] in mm
    """
    pre = np.array([(east_mm[i], north_mm[i], up_mm[i]) for i in range(n_pre_days)])
    pre_avg = pre.mean(axis=0)
    post = np.array([east_mm[-1], north_mm[-1], up_mm[-1]])
    return post - pre_avg


def plot_enu_timeseries(dates, east_mm, north_mm, up_mm, quake_date,
                         station_label, quake_label, outname,
                         day_interval=1):
    """
    Produce a 3-panel East/North/Up displacement time series plot
    (matplotlib), matching the style used throughout this project,
    with a red dashed vertical line marking the earthquake date.

    Saves the figure to outname (PNG, 150 dpi) and returns the path.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    for ax, data, label in zip(
        axes, [east_mm, north_mm, up_mm], ["East (mm)", "North (mm)", "Up (mm)"]
    ):
        ax.plot(dates, data, "-o", color="#1f77b4", markersize=6)
        ax.axvline(quake_date, color="red", linestyle="--", linewidth=1.5)
        ax.set_ylabel(label)
        ax.grid(True, alpha=0.3)

    axes[0].set_title(
        f"GNSS Station {station_label} - Real ENU Displacement (NGL)\n{quake_label}"
    )
    axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=day_interval))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate(rotation=30)
    plt.tight_layout()
    plt.savefig(outname, dpi=150)
    plt.close(fig)
    return outname


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/lon points (degrees)."""
    import math
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def rank_stations_by_distance(epicenter, stations):
    """
    Rank a dict of {station_code: (lat, lon)} by distance from an
    (lat, lon) epicenter. Returns a list of (distance_km, code, lat, lon)
    sorted ascending.
    """
    results = []
    for code, (lat, lon) in stations.items():
        d = haversine_km(epicenter[0], epicenter[1], lat, lon)
        results.append((d, code, lat, lon))
    results.sort()
    return results


# GNSS_IES site code -> NGL site code, where they differ.
# Discovered by matching lat/lon between the GDMS GNSS_IES station list
# and the NGL station page for the guessed/candidate code.
STATION_CODE_MAP = {
    "PAOL": "PAO1",
    "S106": "T106",
    "YENC": "YEN2",
    "SCHN": "SCH7",
    # Stations below use the same code in both systems (no remapping needed):
    # S169, LNCH, DONA, WLIP, JPEI, KNKO, LSAN, WUKU, S101 (Tatun case)
}

# Stations found to have NO NGL coverage for their target earthquake window
# (data ends before the quake, or the station wasn't yet operational):
STATIONS_WITHOUT_NGL_COVERAGE = {
    "TSHO": "NGL data ends 2007 -- no 2016 Meinong-window coverage",
    "YENC": "NGL (YEN2) data ends 2009-04 -- no 2016 Meinong-window coverage",
    "PNSI": "NGL data ends 2022-07 -- no 2024 Hualien-window coverage",
}
