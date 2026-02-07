#!/bin/bash
export $(grep -v '^#' .env | xargs)
export PYTHONPATH=$PYTHONPATH:.
python3 tests/test_retrieval.py
