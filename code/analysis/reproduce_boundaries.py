"""Re-run the candidate-change experiment on all 42 holes and redraw the score figure.

  python reproduce_boundaries.py --data-root ../../data --sqlite <HyLogger_Dataset_Package.sqlite>

The summary CSVs are found by file name anywhere under --data-root. Results go to --out
(default: output/): one boundaries.json per hole, a per-hole CSV, a summary JSON and the figure.
Needs numpy, scipy and matplotlib.

Author: Ding Qing
Date: 2026-10-15
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "scripts"))

# Hole -> WAMEX CollarId whose company log is used as the reference.
# CMDD001/002 use the logs filed with report 103450, because the primary CMDD002 log has no codes.
# The ten after the TBDD holes were drawn at random (seed 20261015) from the 897 catalogue holes that have a
# summary CSV, a verified collar identity and at least three company-log code changes.
HOLES = {
    "CMDD001": 3663110, "CMDD002": 3663111,
    "EHD001": 5481171, "DRDD380": 4867445, "RBDD008": 5212828,
    "TBDD126": 2146094, "TBDD127": 2146095, "TBDD128": 2146096,
    "09THD028": 1505929, "12DHDD0002": 2085822, "15BRDD001": 3836426, "BBDD0011": 4125333,
    "BCMH0072": 5150258, "JLS14DD002": 3681327, "LJM-D007": 2303382, "NDD17002": 4233929,
    "TUR13DD003": 3601187, "UGD4107": 4755491,
    # Second random draw (seed 20261016) of 24 more holes from the remaining eligible holes.
    "17SRDD0004": 4256703, "20CFRCD003": 4872347, "22ACHD0001": 5362728, "AED022": 4906711,
    "AMDD003": 3414740, "BNRD023": 4245097, "CCUD001": 4056036, "CYDD0220": 3768616,
    "HCRD0051": 3098852, "KDD001": 4286900, "MDDH0003": 3243823, "MFED069": 3829212,
    "MG19-003": 4563581, "MNDD0003": 1341068, "MOD7": 2145262, "MVRC041D": 2632760,
    "PLRCD001": 3612927, "RAGD039": 4944618, "RRLGDDD063": 2656153, "SCDD002": 4020100,
    "SCDD003": 4020101, "SGD001": 1557156, "TUR13DD004": 3601191, "YARDDH003": 3836678,
}
DEVELOPMENT = ["CMDD001", "CMDD002"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--sqlite", required=True, type=Path)
    ap.add_argument("--out", default=HERE / "output", type=Path)
    a = ap.parse_args()

    args = ["run_boundary_experiment.py", "--sqlite", str(a.sqlite), "--out", str(a.out),
            "--dev", ",".join(DEVELOPMENT)]
    for hole, collar in HOLES.items():
        found = sorted(a.data_root.rglob(f"SM_{hole}.csv"))
        if not found:
            sys.exit(f"SM_{hole}.csv not found under {a.data_root}")
        args += ["--hole", f"{hole}={found[0]}={collar}"]

    import run_boundary_experiment
    import plot_boundaries
    sys.argv = args
    run_boundary_experiment.main()
    figure = a.out / "fig_boundary_scores_test_holes.png"
    plot_boundaries.score_figure(a.out / "boundary_experiment_summary.json", a.out, figure)
    plot_boundaries.hits_figure(a.out / "boundary_experiment_summary.json", a.out, a.out / "fig_hits_vs_random.png")
    print("figures:", figure, a.out / "fig_hits_vs_random.png")


if __name__ == "__main__":
    main()
