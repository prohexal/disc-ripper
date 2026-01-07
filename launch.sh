#!/bin/bash
# Disc Ripper Launcher - Starts the app detached from terminal

cd "$(dirname "$0")"
nohup /opt/homebrew/bin/python3.11 disc_ripper.py > /dev/null 2>&1 &
echo "Disc Ripper started in background"
