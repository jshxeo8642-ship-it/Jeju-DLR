"""Replaceable degradation model. This initial model is NOT strength loss.

Output: equivalent hours at reference temperature. Its activation energy is
an explicitly uncalibrated demonstration parameter for ASCC/TW.
"""
import numpy as np

GAS_CONSTANT_J_MOL_K = 8.314462618


class ArrheniusEquivalentHours:
    unit = "equivalent_hours"
    monotonic_temperature_response = True

    def __init__(self, settings):
        self.reference_kelvin = settings["reference_temperature_c"] + 273.15
        self.energy_over_r = settings["activation_energy_j_mol"] / GAS_CONSTANT_J_MOL_K

    def rate_per_hour(self, temperature_c):
        """Equivalent reference-temperature hours per elapsed hour."""
        return np.exp(self.energy_over_r * (1 / self.reference_kelvin - 1 / (temperature_c + 273.15)))


def build_model(settings):
    if settings["model"] == "arrhenius_equivalent_hours":
        return ArrheniusEquivalentHours(settings)
    raise ValueError(f"지원하지 않는 열화모델: {settings['model']}")
