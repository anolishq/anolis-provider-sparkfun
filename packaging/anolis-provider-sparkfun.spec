# PyInstaller spec: one self-contained executable, bin/anolis-provider-sparkfun in
# the release tarball. Build with `just freeze`; the result is dist/anolis-provider-sparkfun.
# -*- mode: python -*-

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

# qwiic_i2c picks its platform backend at import time with __import__ on a name
# from a table, which a static import scan cannot follow: take every backend.
# The CircuitPython and MicroPython ones fail to import on Linux and are skipped
# by qwiic_i2c itself.
hiddenimports = collect_submodules("qwiic_i2c")
datas = (
    # importlib.metadata lookups: the provider and the SDK report their versions from these.
    copy_metadata("anolis-provider-sparkfun")
    + copy_metadata("anolis-provider-sdk")
)

a = Analysis(
    ["entry.py"],
    hiddenimports=hiddenimports,
    datas=datas,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="anolis-provider-sparkfun",
    console=True,
    strip=False,
    upx=False,
)
