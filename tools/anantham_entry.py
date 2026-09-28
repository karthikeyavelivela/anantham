"""Frozen-executable entry point: no arguments → GUI; otherwise the CLI."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from anantham.cli import main

    main()
