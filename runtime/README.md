# Runtime

The Windows x64 package includes Python 3.12.14 and NumPy 2.3.5. Double-click **CoreToMap.exe** in the project folder. Keep this directory beside **code/** and **data/**.

Python and NumPy retain their original licences. See **LICENSE.txt**, **SOURCE.txt** and **Lib/site-packages/numpy-2.3.5.dist-info/LICENSE.txt**.

For a source installation without the bundled runtime, install Python 3.12 or newer and run:

```powershell
python -m pip install -r code/requirements.txt
python -B code/launch.py
```
