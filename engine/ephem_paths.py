"""Where the engine's big binary inputs live. None of them are in git.

  DE431      JPL planetary ephemeris, 3.4 GB. Lives in the kaalshodh checkout and is NOT copied:
             set OCCULT_DE431 to its path, or keep kaalshodh beside this repo (the default).
  ephemeris/ this repo, gitignored:
               jup365.bsp   JPL Jupiter satellites, 1.1 GB   naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/
               sat441.bsp   JPL Saturn satellites, 630 MB    (same place)
               lola/        LRO LOLA LDEM_64 + LDEM_16 (PDS) and the NAIF lunar-orientation kernels
                            moon_pa_de421_1900-2050.bpc, pck00010.tpc, moon_080317.tf
"""

import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EPHEM_DIR = os.path.join(REPO, "ephemeris")
DE431 = os.environ.get("OCCULT_DE431") or os.path.abspath(os.path.join(REPO, "..", "kaalshodh", "api", "de431t.bsp"))

if not os.path.exists(DE431):
    raise SystemExit(f"DE431 not found at {DE431}. Set OCCULT_DE431 to the path of de431t.bsp "
                     f"(it lives in the kaalshodh checkout: api/de431t.bsp).")
