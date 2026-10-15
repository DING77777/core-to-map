# Saved mineral-change data

The static viewer uses one generated JavaScript data file per drillhole and an index. These files are created from source summaries and are not tracked in the repository.

Use **Calculate mineral changes** in the application after downloading summary logs and installing NumPy. The application stores new results in `code/work/change-viewer/`.

To regenerate this static viewer collection, run from the package root:

```powershell
python -B code/analysis/build_viewer.py --data data
```

Keep generated data out of GitHub. Source links and placement instructions are in [data/README.md](../../../../data/README.md).
