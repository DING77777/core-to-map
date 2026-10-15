"""Scalar definitions for the reviewed GSWA summary format.

Author: Ding Qing
Date: 2026-10-15
"""

import re

METRIC_ID = "2200W_AlOH"
LEGACY_METRIC_ID = "aloh_2200w_summary"
PRODUCT = "GSWA TSG Summary Mineral Log"

SWIR_GROUPS = (
    "Kaolin", "White-Mica", "Smectite", "Other-AlOH", "Chlorite", "Dark-Mica",
    "Amphibole", "Serpentine", "Other-MgOH", "Epidote", "Tourmaline", "Carbonate", "Sulphate", "Invalid",
)
TIR_GROUPS = (
    "Misc-Silicate", "Silica", "K-Feldspar", "Plagioclase", "Garnet", "Pyroxene", "Olivine", "Zeolite",
    "Kaolin", "White-Mica", "Smectite", "Other-AlOH", "Chlorite", "Dark-Mica", "Amphibole", "Serpentine",
    "Other-MgOH", "Epidote", "Tourmaline", "Carbonate", "Sulphate", "Phosphate", "Oxide", "INVALID",
)
FEATURES = ("900D_Fe", "900W_Fe", "1900D_Water", "2200D_AlOH", "2200W_AlOH", "2250D_FeOH", "2250W_FeOH", "8625D_Quartz", "11300D_Carbonate", "11300W_Carbonate")


def _metric(field):
    item = {
        "metric_id": field, "source_field": field, "product": PRODUCT,
        "minimum_valid_value": 0, "allowed_operations": ["gte", "continuous_interval_search"],
        "summary_method": "Reported one-metre summary; the within-bin calculation is not verified for every field.",
        "missing_policy": {"N.A.": "Not detected or below threshold", "gap": "No source record; never filled with zero"},
        "registry_version": "2.0",
    }
    mineral = re.fullmatch(r"(.+)_\(System_(SWIR|TIR)\)", field)
    feature = re.fullmatch(r"(\d+)([WD])_(.+)", field)
    if mineral:
        name, region = mineral.groups()
        invalid = name.lower() == "invalid"
        item.update(
            label=f"{'Unclassified' if invalid else name.replace('-', ' ')} · {region}",
            unit="relative proportion", unit_status="reported_relative_spectral_proportion",
            kind="quality_proportion" if invalid else "mineral_group_proportion",
            group="Quality" if invalid else f"Mineral groups · {region}", region=region,
            interpretation_level="System", algorithm="TSA+" if region == "SWIR" else "jCLST",
            definition=("Reported unclassified proportion: aspectral, noisy, low-albedo or high-error results."
                        if invalid else "Reported relative spectral group contribution from automated unmixing; not a measured mass fraction."),
            definition_source="Source CSV System and group metadata", default_threshold=0.2,
        )
    elif feature:
        wavelength, mode, assignment = feature.groups()
        region = "TIR" if int(wavelength) > 2500 else "VNIR" if int(wavelength) < 1300 else "SWIR"
        is_wavelength = mode == "W"
        item.update(
            label=f"{assignment} · {wavelength}{mode}", unit="nm" if is_wavelength else "dimensionless",
            unit_status="defined_by_source_metadata", region=region, group="Spectral features",
            kind="spectral_feature_wavelength" if is_wavelength else "spectral_feature_depth",
            interpretation_level="not_applicable_to_feature_scalar",
            algorithm="source feature extraction",
            definition=("Wavelength of the dominant spectral feature, labelled by its typical assignment."
                        if is_wavelength else "Background-normalised depth of the dominant spectral feature; this is absorption strength, not downhole depth."),
            definition_source=f"Source CSV metadata row ****{mode}",
            default_threshold=int(wavelength) if is_wavelength else 0.01,
        )
    else:
        item.update(label="VIS–SWIR albedo", unit="source units", unit_status="scale_not_declared_in_csv",
                    region="VIS–SWIR", group="Other scalars", kind="albedo", interpretation_level="not_applicable",
                    algorithm="source scalar", definition="Reported VIS–SWIR albedo. The CSV does not declare its calibration or scale.",
                    definition_source="Source column name", default_threshold=0.2)
    return item


FIELDS = tuple(f"{name}_(System_SWIR)" for name in SWIR_GROUPS) + ("VIS-SWIR_Albedo",) + FEATURES[:7] + tuple(f"{name}_(System_TIR)" for name in TIR_GROUPS) + FEATURES[7:]
METRIC_REGISTRY = {field: _metric(field) for field in FIELDS}


def canonical_metric(metric_id):
    return METRIC_ID if metric_id == LEGACY_METRIC_ID else metric_id

