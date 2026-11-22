"""Keep a deployment alive; the experiment is a separate TACC client job."""

import os
import time

print("SERVICE_MODE=deployment-only", flush=True)
print("CLIENT_MODE=submit-separate-tcloud-job", flush=True)
print("STOP_SERVICE_WITH=tcloud cancel -j " + os.environ["SLURM_JOB_ID"], flush=True)
while True:
    time.sleep(60)
