"""IEEE 738-2023 SI heat terms; isothermal conductor approximation.

Solar input is DNI at the site (already altitude-adjusted). No GHI conversion.
Equations (7), (9)-(19), (21), (23)-(27), (33). See docs/MODEL_NOTES.md.
"""
from datetime import timezone
import numpy as np


def resistance(temperature, conductor):
    r = conductor["resistance"]
    low = r["r25_ohm_m"]
    slope = np.where(temperature <= 100,
                     (r["r75_ohm_m"] - low) / 50,
                     (r["r200_ohm_m"] - low) / 175)
    result = low + slope * (temperature - 25)
    if np.any(result <= 0):
        raise ValueError("온도 범위에서 계산된 도체 저항이 양수가 아닙니다.")
    return result


def wind_angle_factor(wind_direction, span_azimuth):
    difference = np.mod(np.abs(wind_direction - span_azimuth), 180)
    phi = np.deg2rad(np.minimum(difference, 180 - difference))
    return 1.194 - np.cos(phi) + 0.194 * np.cos(2 * phi) + 0.368 * np.sin(2 * phi)


def convection(temperature, ambient, wind, angle_factor, diameter, elevation):
    film = (temperature + ambient) / 2
    rho = (1.293 - 1.525e-4 * elevation + 6.379e-9 * elevation**2) / (1 + 0.00367 * film)
    mu = 1.458e-6 * (film + 273)**1.5 / (film + 383.4)
    k = 2.424e-2 + 7.477e-5 * film - 4.407e-9 * film**2
    re = diameter * rho * wind / mu
    delta = temperature - ambient
    magnitude = np.abs(delta)
    natural = 3.645 * np.sqrt(rho) * diameter**0.75 * magnitude**1.25
    forced1 = angle_factor * (1.01 + 1.35 * re**0.52) * k * magnitude
    forced2 = angle_factor * 0.754 * re**0.6 * k * magnitude
    forced = np.where(wind > 0, np.maximum(forced1, forced2), 0)
    # Signed extension below ambient: convection heats a colder conductor.
    return np.sign(delta) * np.maximum(natural, forced)


def radiation(temperature, ambient, diameter, emissivity):
    return 17.8 * diameter * emissivity * (((temperature + 273) / 100)**4 - ((ambient + 273) / 100)**4)


def solar_projection(instant, spans):
    """DNI projection on a horizontal conductor; approximate apparent solar time.

    UTC+longitude+equation-of-time avoids treating civil noon as solar noon.
    Solar-vector formulation avoids the arctan quadrant singularity at noon.
    """
    utc = instant.astimezone(timezone.utc)
    day = utc.timetuple().tm_yday
    b = 2 * np.pi * (day - 81) / 364
    equation_minutes = 9.87 * np.sin(2 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)
    declination = np.deg2rad(23.45 * np.sin(np.deg2rad(360 * (284 + day) / 365)))
    lat = np.deg2rad([s["latitude_deg"] for s in spans])
    lon = np.array([s["longitude_deg"] for s in spans])
    az = np.deg2rad([s["azimuth_deg"] for s in spans])
    hour = utc.hour + utc.minute / 60 + utc.second / 3600
    omega = np.deg2rad((hour + lon / 15 + equation_minutes / 60 - 12) * 15)
    east = -np.cos(declination) * np.sin(omega)
    north = np.cos(lat) * np.sin(declination) - np.sin(lat) * np.cos(declination) * np.cos(omega)
    up = np.sin(lat) * np.sin(declination) + np.cos(lat) * np.cos(declination) * np.cos(omega)
    dot = east * np.sin(az) + north * np.cos(az)
    return np.where(up > 0, np.sqrt(np.maximum(0, 1 - dot**2)), 0)


def temperature_rate(temperature, current, ambient, wind, angle, solar_gain, conductor, elevation):
    return (current**2 * resistance(temperature, conductor) + solar_gain
            - convection(temperature, ambient, wind, angle, conductor["diameter_m"], elevation)
            - radiation(temperature, ambient, conductor["diameter_m"], conductor["emissivity"])) / conductor["heat_capacity_j_m_k"]
