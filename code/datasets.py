"""Reviewed source files and display groups.

Author: Ding Qing
Date: 2026-10-15
"""

SOURCES = {
    "CMDD001": ("nvcl_wa/CMDD001/supporting/SM_CMDD001.csv", "839e89f496a2d01919c37c77e6fac6968e51868d70a75792072012fa27e3d4bb"),
    "CMDD002": ("nvcl_wa/CMDD002/supporting/SM_CMDD002.csv", "184f516414a92c87faedcb03659d9e05aa29145e445e6d50735fdd601444a036"),
    "EHD001": ("new_holes_20261015/SM_EHD001.csv", "41219905de15fcbb627687c98c82414149c0ea4d3b9ab36ae3c0112c648d4cfb"),
    "DRDD380": ("new_holes_20261015/SM_DRDD380.csv", "c300d430583094ce915eac868f9d37f7dc1c408a6df528fb664687d09c1cb11e"),
    "RBDD008": ("new_holes_20261015/SM_RBDD008.csv", "dbf7ccf03cd944057a6a93c3610fafa3cacea153594ded221ba50581e235075a"),
    "TBDD126": ("cluster_tbdd_20261015/SM_TBDD126.csv", "595543f37b59b06196c913a5e09a77413a6695c131be9aab9248010140c31e7a"),
    "TBDD127": ("cluster_tbdd_20261015/SM_TBDD127.csv", "2ad40360e857c09f4ade65e580d53c931a7deb00f71a1dcd4e4d154914cb5642"),
    "TBDD128": ("cluster_tbdd_20261015/SM_TBDD128.csv", "37e25ebe6fe12dd86f082ac25fe024646748d79381c49dd27446544bdf938429"),
}

LOADED_HOLES = tuple(SOURCES)
DEFAULT_HOLES = ("CMDD001", "CMDD002")
DEMO_HOLES = ("TBDD126", "TBDD127", "TBDD128")
GROUPS = [
    {"id": "tbdd", "label": "TBDD · local comparison", "hole_ids": list(DEMO_HOLES), "depth_from_m": 96, "depth_to_m": 175},
    {"id": "cmdd", "label": "CMDD · source detail", "hole_ids": list(DEFAULT_HOLES), "depth_from_m": 0, "depth_to_m": 150},
    {"id": "regional", "label": "Other WA projects", "hole_ids": ["EHD001", "DRDD380", "RBDD008"], "depth_from_m": 0, "depth_to_m": 1312},
]

