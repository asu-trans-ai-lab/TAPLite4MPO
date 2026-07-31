#!/usr/bin/env python3
"""Run one TAPLite assignment through the native shared library in cwd."""

import argparse
import ctypes
import os
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library")
    args = parser.parse_args()

    library = ctypes.CDLL(os.path.abspath(args.library))
    run = library.DTA_AssignmentAPIWithStatus
    run.argtypes = []
    run.restype = ctypes.c_int
    return int(run())


if __name__ == "__main__":
    sys.exit(main())
