#!/bin/bash
cd frontend
# logs to run_frontend.log in the root/frontend dir
nohup npm run dev > run_frontend.log 2>&1 &
echo $! > frontend_pid.txt
echo "Frontend started with PID $(cat frontend_pid.txt)"
