# E-Waste Compute Grid: implementation review and next steps

Reviewed on 7 October 2026 against both supplied PDFs and the source in this workspace.

## Assessment

The project has a working foundation for distributed batch execution. The backend, worker agent, inference script, and dashboard share an operational path. This is more than a UI prototype. However, the current checkout does not demonstrate the complete team objective: three physical, heterogeneous devices processing a real workload, recovery after killing a worker, visible task ownership, and defensible performance and energy reporting.

The most immediate explanation for surprising AI output is the sample dataset. It contains synthetic shapes and blank placeholders instead of the named objects. A second source of confusion is that the submission form defaults to a deterministic dummy workload. Some advanced modules also exist only as standalone utilities; their tests passing does not make them features of the live grid.

The documents were treated as project requirements to evaluate, including their phase exit criteria. Their embedded directions to coding agents were not treated as a request to implement or deploy everything during this review. No application source was changed.

## 1. Define the desired output

Your product is a coordinator for useful computation on enrolled hardware. The demonstration workload implemented here is **image classification with MobileNetV2**. It produces a class label and confidence for each image. It does not produce bounding boxes, train an AI model across computers, generate images, or merge machines into one large GPU.

For a controlled demonstration, use 300 real photos and a chunk size of 25. This should create 12 tasks. Start at least three physical workers before submitting the job. Workers should claim compatible tasks, execute them, upload output, and continue claiming work until the queue is drained. Faster machines may finish more tasks; equal allocation is not required. To demonstrate simultaneous participation, choose enough work that one worker cannot drain the queue before others poll.

Expected observable outputs:

| Output | Acceptance criterion |
| --- | --- |
| Worker registry | Three distinct physical machines appear with their CPU/RAM and supported workload |
| Distribution | At least three machines process tasks from the same job, with overlapping execution intervals |
| Progress | Job moves from QUEUED to IN_PROGRESS to COMPLETED |
| Result artifact | Downloaded job JSON accounts for all 300 inputs; with clean images, 300 predictions and zero errors |
| Fault recovery | A worker is killed while holding an unfinished task; another worker completes that same task with a new attempt identity |
| Correct counting | Completed tasks and successful predictions are not counted twice after a retry |
| Performance | Job elapsed time, per-task duration, throughput, and contributing workers are reported |
| Energy | Estimated or measured Wh are reported with their scope and method |
| Reuse evidence | Identify the actual retired/underused devices used and the useful work delivered |

For a batch with an intentionally corrupted image, PARTIAL_SUCCESS and an explicit error for that image are valid outputs. A classification label can be wrong without the distributed system failing; check inference quality separately from task-delivery correctness.

## 2. What I verified

| Check | Result |
| --- | --- |
| Backend Prisma generation and TypeScript build | Passed |
| Backend validation tests | 3 passed |
| Real PostgreSQL/HTTP integration suite | 11 passed, bringing backend total to 14 |
| Worker unit tests | 7 passed |
| Workload, scoring, fault-tolerance, and energy tests | 17 passed |
| Frontend production build | Passed |
| Frontend lint | Passed |
| Direct MobileNet inference on supplied sample directory | 10 items processed, zero execution errors; predictions unsuitable as semantic demo evidence |
| Model SHA-256 | Matches the expected checksum in the repository |

The integration suite exercised authenticated registration, idempotent jobs, concurrent claims, capability/RAM filtering, duplicate completions, expired leases, stale-attempt rejection, retry limits, partial results, two real Python workers, and real inference with corrupt input.

Important limits: those workers ran as local processes in native execution mode. The lease tests force expiration through database state; they do not substitute for killing a physical worker in front of judges. Docker workload execution, three-device networking, ARM hardware, and deployed AWS resources were not verified. The frontend was built and linted, but its browser interactions were not exercised.

For testing, I used a separate temporary PostgreSQL container and test schemas. The container and its temporary data were removed after the checks. Your configured application database was not modified.

## 3. Concrete findings

### A. Sample images are placeholders: fix this first

`workloads/test-data/sample/cat.jpg` is a brown background with a white rectangular border. The five files `airliner.jpg`, `coffee_mug.jpg`, `golden_retriever.jpg`, `sports_car.jpg`, and `tabby_cat.jpg` are identical solid-color images. Their RGB extrema are constant throughout each image. Other samples are synthetic shapes rather than photographs of the named subjects.

The setup script creates a solid-color fallback when an image download fails. On later runs it skips any existing file over 1,000 bytes, which includes those fallbacks. Thus, a failed download can leave a placeholder permanently masquerading as a valid demo photo.

Direct inference reproduced the existing surprising output: `cat.jpg` became `envelope` at 0.151 confidence; the solid-color `golden_retriever.jpg` became `kite` at 0.0667. The model is receiving pixels, not the meaning of the filename.

Action: replace the demo dataset with genuine, inspectable photos. Separate synthetic pipeline fixtures from semantic evaluation images. Make the downloader fail visibly or mark fallback files as synthetic instead of reporting them as a ready realistic dataset. Establish a small labeled set and record classification accuracy; do not demand that every photo gets the expected top label.

### B. The default UI job generates mock predictions

`frontend/src/App.tsx` defaults to `dummy`, displayed as "Pipeline demo". `run_dummy.py` creates `dummy_class_*` labels from a filename hash. Its role is testing orchestration. To obtain real model predictions, select "Image classification" and upload actual images.

### C. This checkout's startup environment is inconsistent

The `.venv` launcher references `C:\Users\BIT\AppData\Local\Programs\Python\Python312\python.exe`, which is unavailable on this machine. It cannot be used as a portable environment. I ran the Python checks with the bundled Python 3.12 interpreter and compatible packages already present in the copied environment.

The current backend `.env` points to `localhost:5432/ewaste_proj`. The Compose database is exposed to host processes on port 55432 with database `ewaste`. The example environment file uses that Compose address. Docker had no running containers when inspected. These observations explain why a frontend alone cannot make the grid operate; they do not prove which exact error you saw during earlier runs.

The worker defaults to Docker execution and verifies both configured workload images at startup. Those `ewaste/*:v1` images were absent from the local Docker image inventory. Consequently, starting a physical Docker-mode worker requires building or loading both images first.

The folder also has no Git repository metadata. The CI workflow exists in the files, but its remote execution cannot be inferred from this copied folder.

### D. The live scheduler is capability-aware FIFO

In `control-plane/src/app.ts`, task requests filter by workload capability and minimum RAM, then select the oldest compatible queued task with `FOR UPDATE SKIP LOCKED`. This is a reasonable basic pull scheduler, and the concurrent-assignment tests pass.

`workloads/scheduler_scorer.py` is not called by the control plane or worker. The worker imports the hardware classifier but does not run `run_full_benchmark()` at enrollment. The database lacks the benchmark throughput, resource-load, score, and selection-rationale fields needed for the advanced scheduling story.

Action: first collect genuine per-machine inference throughput. Then implement a defined scoring policy in the actual scheduling path, persist its inputs and decision, and expose the rationale. A Python ranking function operating on fixture dictionaries does not establish energy-aware assignment in this pull-based server. Decide explicitly how an eligible low-ranked worker is admitted or deferred so work is not starved.

The standalone benchmark uses additional capability names such as `image_classification` and `onnx_cpu`, while registration permits `dummy` and `image_inference`. Add a deliberate adapter or revise the shared contract before connecting these modules.

### E. The dashboard hides the most important demonstration evidence

The UI already shows live nodes, aggregate cores, completed tasks, estimated energy, per-job progress, and a JSON download. It does not show task-to-worker allocation, current task identifiers, retry attempts, reassignment history, per-worker completed counts, average task time, job elapsed time, scores, or readable classification results.

The backend returns global task status counts, but the UI does not render them. There is no task-detail/event-history endpoint for the frontend. A node turning OFFLINE is insufficient to explain which abandoned task was rescued.

Action: add a per-job task table and transition history. Each row should include task ID, worker, state, attempt, start/end times, error, and duration. Store assignment/recovery events so the UI can show the old and new owner. Add a result table with image, label, and confidence, and a per-job metrics summary.

### F. Energy modules exist, but the live path reports estimates only

The backend calculates energy as `baselinePowerW * executionTimeMs / 3_600_000` for accepted completed tasks. Both dashboard and job results label it ESTIMATED. The worker does not call the power-meter utility, and the schema has no measured-power provenance or measured-vs-estimated field per task.

This is an estimate of successful execution only. It excludes failed/retried attempts, idle workers, data transfer, and control-plane energy. Hardware type is inferred largely from architecture, cores, and RAM; that heuristic can classify a laptop as a desktop and is not a power measurement.

Also, the job's `execution_time_ms` sums task durations. It is cumulative compute time, not elapsed job time. Three concurrent ten-second tasks sum to roughly thirty seconds while the job may finish in roughly ten seconds plus overhead.

Action: report job elapsed time separately. Add energy records for attempts, measurement type/source, and a device inventory with calibrated or explicitly assumed wattage. If using a meter, integrate the measurement into the worker execution path and retain that evidence through the API.

The standalone savings functions assume a hypothetical 200 W system running for the same duration. That is not a same-work measured cloud baseline. Keep such comparisons explicitly hypothetical; successful compute hours are evidence of useful work, not proof of a particular amount of hardware lifespan extension or avoided manufacturing emissions.

### G. Failure recovery works in tests, but its demo timing needs planning

Default settings are a five-minute task lease, a 90-second offline threshold, and a ten-second recovery sweep. Heartbeats extend active leases. Killing a worker can make it appear offline substantially before its task becomes available again.

Action: rehearse an abrupt process kill while the worker has an assigned task. Use a clearly documented demo lease of approximately 30 seconds, a heartbeat around five seconds, and a sweep around two seconds. Keep the lease safely above ordinary heartbeat/network delays and let the server's returned heartbeat interval remain authoritative. Freeze those settings after rehearsal. An ordinary short batch may finish before anyone can disconnect a worker; choose a sufficiently long real batch. Use dummy delay only for a separately labeled recovery rehearsal.

### H. AWS integration remains unproven

The backend has an actual S3 storage driver and presigned URL support. However, this checkout has no AWS deployment templates/scripts or deployed-resource evidence. The "cloud runtime validator" copies local images and performs local inference; it is explicitly a simulation. Its passing result would not establish S3 transfers or a cloud-hosted control plane.

Action: after the LAN demo is reliable, deploy the existing architecture, configure reachable HTTPS API/storage addresses, secrets, bucket permissions, and logging, then run workers through that deployment. Decide which AWS services the event actually requires. Keeping PostgreSQL as the MVP queue is a deliberate departure from the earlier Redis/SQS specification; record the choice rather than replacing a working queue without a reason.

### I. Documentation completion claims exceed the live implementation

`workloads/README.md` marks phases 0–7 complete and links multiple documents that are absent from `docs/`. The API contract is also outdated: it omits required registration identity, worker authentication, job admin/idempotency headers, uploaded input objects, lease tokens, and result-key completion.

The Python helper `task_runner.py` returns camelCase completion objects that the active API does not accept directly. The active worker instead uses `worker/task_executor.py` and `worker/api_client.py`. The standalone Python aggregator is likewise separate from the server's result endpoint.

Action: document the active path, update payload examples from passing integration tests, and replace phase checkmarks with the corresponding demonstrated exit criteria. Avoid maintaining two supposedly canonical runners, aggregators, and contracts without explicit boundaries.

## 4. Team work order

| Order | Owner | Deliverable and gate |
| --- | --- | --- |
| 1 | Nikhil | Real photos, small labeled evaluation set, verified model output, genuine throughput measurements |
| 2 | Vaibhav + Kushagra | Clean startup instructions; one worker completes one real task through backend storage and result download |
| 3 | Vaibhav + Nikhil | Three physical devices on a shared LAN; workload images and runtimes verified on each |
| 4 | Kushagra + Chinmay | Task ownership/retry API and dashboard; per-job timing and readable results |
| 5 | All | Same real batch spans three devices; abrupt worker kill recovers without duplicate output |
| 6 | Nikhil + Vaibhav + Kushagra | Energy scope/provenance, one measured device if available, per-job and per-node metrics |
| 7 | Kushagra + Nikhil + Chinmay | Live benchmark-based scheduling and selection rationale, after the basic demo passes |
| 8 | Vaibhav + Kushagra + Chinmay | AWS deployment with real storage/API transfers; repeat the exact same acceptance demo |

Do not start by adding more workload types or redesigning the whole system. The immediate milestone is a reproducible real-workload run with clear evidence.

## 5. Practical startup sequence

For a simulated local integration environment, from the workspace root:

```powershell
docker compose -f infra/docker-compose.yml up --build
```

This configuration launches PostgreSQL, the backend, frontend, and two native-mode simulation workers. It uses a PostgreSQL 16 image and may need downloads/builds. Open `http://localhost:5173`; with unchanged Compose defaults, the dashboard admin token is `local-admin-change-me`. Confirm nodes are visible before submitting work. This is an integration rehearsal; it does not satisfy the three-physical-device objective.

For physical Docker-mode workers, build or load both workload images on each participating machine:

```powershell
docker build -t ewaste/dummy-workload:v1 workloads/dummy-workload
docker build -t ewaste/ai-workload:v1 workloads/ai-inference
```

Install a supported Python 3.12 interpreter and create a fresh local environment, for example `.venv-local`, rather than relying on the copied `.venv`. Install `worker/requirements.txt` into it. ONNX/Pillow/NumPy host dependencies are additionally needed for native mode; Docker mode bundles inference dependencies inside the workload image.

Set worker `CONTROL_PLANE_URL` to `http://<server-LAN-IP>:8080/api`, use the backend's matching enrollment token, and give each physical machine a distinct worker name. The backend's `PUBLIC_API_URL` must also be reachable by those workers. Run the agent with that fresh environment's Python executable. In Docker mode, Docker must be running and both images must be available before registration.

If running the backend directly on the host against the Compose database, use the host-facing port 55432 and database `ewaste`, with the configured password. Inside Compose, the backend uses `db:5432`. Do not mix those addresses with the existing unrelated `.env` database setting. If you intentionally use a separately installed PostgreSQL instance, create/synchronize the schema there and document that choice instead.

For meaningful backend verification, set `TEST_DATABASE_URL` to a disposable database and `TEST_PYTHON` to your working Python executable before `npm test`. Without `TEST_DATABASE_URL`, the database integration suite is skipped. Do not use a shared production database for integration tests.

## 6. Final demo acceptance checklist

- Three physically distinct enrolled devices contribute to one real image job.
- Screenshots or logs show concurrent execution and task ownership.
- The downloaded output accounts for every submitted input.
- Killing a worker recovers its assigned task on another device.
- Each accepted input result is counted once despite retries.
- Job elapsed time is distinguished from cumulative task runtime.
- Energy numbers identify estimates, measurement source, and excluded costs.
- Hardware inventory establishes which devices are retired or underused.
- Advanced scheduling claims are backed by the live decision path.
- If AWS is presented, workers actually connect through the deployed service and storage.
- A clean checkout and documented commands reproduce the demo without copied virtual environments.

Source specifications: `D:\wemakedev-amazon\E_Waste_Compute_Grid_Hackathon_Documentation.pdf` (especially sections 19–20 and 26) and `D:\wemakedev-amazon\E_Waste_Compute_Grid_Team_Phasewise_Specification.pdf` (phase exit criteria and final team objective).
