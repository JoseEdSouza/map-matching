from datetime import datetime
import os
from pathlib import Path
from typing import Sequence

from gpx import GPX, Waypoint, Track, TrackSegment

type GPSPoint = tuple[float, float, datetime]  # (longitude, latitude, timestamp)


def create_waypoint(point: GPSPoint) -> Waypoint:
    w = Waypoint()
    w.lon, w.lat, w.time = point
    return w


def to_track(points: Sequence[GPSPoint]) -> Track:
    wps = [create_waypoint(p) for p in points]

    ts = TrackSegment()
    ts.points.extend(wps)

    trk = Track()
    trk.trksegs.append(ts)

    return trk


def resolve_absolute(path: Path) -> Path:
    return path.resolve().absolute()

def ensure_filetype(path: Path, suffix: str) -> Path:
    if path.is_dir():
        return resolve_absolute(path / ("dataframe" + suffix))

    os.makedirs(path.parent, exist_ok=True)

    if path.suffix == suffix:
        return resolve_absolute(path)

    new_filetype = path.stem + suffix

    return resolve_absolute(path.parent / new_filetype)


def to_gpx(points: Sequence[GPSPoint], output_path: Path) -> Path:
    """
    Convert waypoints, tracks, and routes to a GPX object.

    :param waypoints: List of waypoints.
    :return: GPX object containing the provided data.
    """
    gpx = GPX()

    trk = to_track(points)

    gpx.tracks.append(trk)

    out = ensure_filetype(output_path, ".gpx")

    gpx.to_file(out)

    return out
