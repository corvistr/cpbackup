#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os
import sys

os.umask(0o077)
sys.path.insert(0, "/opt/cpbackup")

from engine.service import run_worker

if __name__ == "__main__":
    run_worker(service="--service" in sys.argv)
