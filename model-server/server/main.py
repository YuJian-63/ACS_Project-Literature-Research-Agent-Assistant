"""SDK entrypoint; the platform's bootstrap Python launches the course task."""
import os

# Keep the SDK entry PID so termination reaches the shell's forwarding traps.
os.execv("/bin/bash", ["bash", os.path.join(os.environ["TACC_WORKDIR"], "job.sh")])
