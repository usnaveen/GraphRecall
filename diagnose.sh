#!/bin/bash
echo "Current Dir: $(pwd)" > debug_env.txt
echo "PATH: $PATH" >> debug_env.txt
echo "NPM location: $(which npm)" >> debug_env.txt
echo "Node location: $(which node)" >> debug_env.txt
npm --version >> debug_env.txt 2>&1
node --version >> debug_env.txt 2>&1
ls -la frontend/ >> debug_env.txt 2>&1
