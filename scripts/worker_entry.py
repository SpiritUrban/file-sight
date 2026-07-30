"""Entry point for the frozen worker executable.

PyInstaller needs a script, not a module, so this is the thinnest possible
shim over ``filesight.worker.main``. It must stay trivial: anything imported
here is imported before the worker gets a chance to control ordering, and the
import order of the native extensions is load-bearing on Windows.
"""

import multiprocessing
import sys

if __name__ == "__main__":
    # Without this, a frozen build on Windows re-executes the whole program
    # in every worker process torch spawns -- which, for a program that talks
    # a protocol over stdio, means several processes fighting over one pipe.
    multiprocessing.freeze_support()

    from filesight.worker import main

    sys.exit(main())
