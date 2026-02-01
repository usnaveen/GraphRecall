#!/bin/bash
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 backend/scripts/seed_content.py sample_content/DeepLearning.md > seed_output.log 2>&1
echo "Script finished with exit code $?" >> seed_output.log
