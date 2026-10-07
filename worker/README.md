# E-Waste Compute Grid: Worker Agent

This is the Python daemon that runs on edge hardware (old PCs, Raspberry Pis, etc.) to process AI tasks.

## Responsibilities:
- Hardware detection (CPU/RAM) to calculate baseline power.
- Registration and Heartbeat polling.
- Requesting tasks from the Control Plane using exponential backoff to avoid thundering herds.
- Downloading input data securely from pre-signed S3 URLs.
- Triggering local Docker execution securely using bind mounts and host user mapping.
- Uploading output data and submitting metrics back to the Control Plane.

## Prerequisites
- Python 3.8+
- Docker Engine installed and running on the host system.
- Network access to the Control Plane API.

## Setup
1. Create a virtual environment (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment variables (create a `.env` file):
   ```env
   CONTROL_PLANE_URL=http://localhost:8080/api
   ENROLLMENT_TOKEN=HACKATHON_DEFAULT_TOKEN
   ```

## Running the Agent
Run the agent directly on the host machine:
```bash
python agent.py
```
The agent will automatically register with the control plane, save its credentials to `.worker_data/credentials.json`, and begin polling for tasks.

## Troubleshooting
- **Docker Client Error**: If the agent logs `Failed to initialize Docker client`, ensure Docker is running and the user has permissions to access the Docker daemon (e.g., in the `docker` group on Linux).
- **Registration Failed**: Check `CONTROL_PLANE_URL` in your `.env` file and verify the Control Plane backend is running.
