#!/bin/bash
# Install system dependencies
apt-get update -y
apt-get install -y ffmpeg flite
pip install -r requirements.txt
echo "DR SHEMA Video Service build complete"
