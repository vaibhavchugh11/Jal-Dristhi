import numpy as np


def pressure_atm(elev_m):
    return (1.0 - 2.25577e-5 * elev_m) ** 5.25588


def do_saturation_mgl(temp_c, salinity=0.0, elev_m=0.0):
    # oxygen the water can hold (Benson and Krause 1984, the equations USGS uses)
    t = np.asarray(temp_c, dtype=float)
    T = t + 273.15
    lnC = (-139.34411 + 1.575701e5 / T - 6.642308e7 / T ** 2
           + 1.243800e10 / T ** 3 - 8.621949e11 / T ** 4)
    lnC = lnC - np.asarray(salinity, dtype=float) * (1.7674e-2 - 1.0754e1 / T + 2.1407e3 / T ** 2)
    C = np.exp(lnC)
    P = pressure_atm(elev_m)
    if abs(P - 1.0) < 1e-12:
        return C
    pw = np.exp(11.8571 - 3840.70 / T - 216961.0 / T ** 2)
    th = 0.000975 - 1.426e-5 * t + 6.436e-8 * t ** 2
    return C * P * ((1 - pw / P) * (1 - th * P)) / ((1 - pw) * (1 - th))
