# Implemented API contract

Source of truth: `control-plane/src/app.ts`, `pairing.ts`, `validation.ts`, `storage.ts` and
`worker/api_client.py`. This documents the existing v1 behavior; it does not
introduce a new protocol version. Pairing adds a database table and node admission
fields; see [WORKER_ONBOARDING.md](WORKER_ONBOARDING.md) for rollout and API details.

## Authentication and errors

Admin routes use `Authorization: Bearer <ADMIN_TOKEN>`. Registration uses the
separate enrollment token. Every other worker route uses BOTH
`Authorization: Bearer <node_secret>` and `x-node-id: <node_id>`.
Signed storage URLs are temporary credentials: use the exact URL without adding
admin/worker authorization and do not log it. Production transport must be HTTPS.

JSON error shape: `{ "error": "description" }`. Typical status codes are 400
(invalid input/result), 401 (credentials), 403 (node mismatch), 404 (not found),
409 (stale lease or conflicting idempotency key), 413 (body too large), 500
(internal failure). JSON requests use `Content-Type: application/json` except
the binary image upload.

## Route inventory

| Method and route | Authentication | Success |
| --- | --- | --- |
| GET `/api/health` | None | 200 database health and storage driver |
| POST `/api/inputs?name=photo.jpg` | Admin | 201 `{key,name}` |
| POST `/api/jobs` | Admin + `Idempotency-Key` | 201 new Job; 200 existing identical Job |
| GET `/api/jobs/:job_id/results` | Admin | 200 downloadable aggregated JSON |
| GET `/api/dashboard/sync` | Admin | 200 current snapshot |
| POST `/api/nodes/register` | Enrollment | 200 worker credentials |
| POST `/api/pairing` | None, rate limited | 201 temporary code/private session |
| POST `/api/pairing/invite` | Admin, rate limited | 200 invitation state |
| GET `/api/pairing/:id` | Private pairing bearer, rate limited | 200 state, no credentials |
| POST `/api/pairing/:id/decision` | Private pairing bearer, rate limited | 200 decision; approval includes worker credentials |
| GET `/api/nodes/session` | Worker | 200 authenticated session, no secret |
| POST `/api/nodes/session` | Worker | 200 refreshed hardware/capabilities and session |
| POST `/api/nodes/:node_id/revoke` | Admin or that worker | 200 REVOKED |
| POST `/api/nodes/:node_id/heartbeat` | Worker | 200 acknowledgement/action |
| GET `/api/tasks/request` | Worker | 200 assignment; 204 no eligible task |
| GET `/api/tasks/:task_id/upload-url` | Worker + `x-lease-token` | 200 signed upload URL/key |
| POST `/api/tasks/:task_id/complete` | Worker | 200 completion acknowledgement |
| POST `/api/tasks/:task_id/fail` | Worker | 200 REQUEUED or FAILED |
| GET `/api/storage` | Signed URL, local driver only | 200 object bytes |
| PUT `/api/storage` | Signed URL, local driver only | 204 result stored |

## Upload and submit

`POST /api/inputs?name=photo.jpg` takes nonempty raw image bytes with
`Content-Type: application/octet-stream`; default maximum is 20 MiB. Extensions:
jpg/jpeg/png/webp/bmp. The server sanitizes the filename and returns, for example:

```json
{"key":"inputs/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/photo.jpg","name":"photo.jpg"}
```

The upload route checks extension and size, not pixel decoding. An invalid image
is reported by the workload. Use the returned object in the job request:

```json
{
  "name": "Ten real photos",
  "workload_type": "image_inference",
  "items": [{"key":"inputs/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/photo.jpg","name":"photo.jpg"}],
  "chunk_size": 5,
  "min_ram_gb": 2
}
```

Send a unique `Idempotency-Key` for each intended submission. Reusing it with
the same normalized body returns the original Job; a different body returns 409.
Response is the Job record, with `id`, `status`, `totalTasks`, `completedTasks`,
`failedTasks`, timestamps and request identity fields. It is not `{job_id: ...}`.
The backend prefixes each image name with its input index, e.g. `00000_photo.jpg`,
so repeated original filenames remain distinct. Workers and outputs use this
exact assigned name.

Limits: 1–10000 items; integer chunk size 1–100 (default 10); RAM requirement
0.25–1024 GiB (default image 2, dummy 0.25). Image objects must reference existing
input keys. Dummy jobs use `"workload_type":"dummy"` and strings in `items`;
the server stages them as indexed `.txt` files. Dummy predictions are synthetic.

## Worker registration and heartbeat

Registration body:

```json
{
  "registration_key": "persistent-per-agent-uuid",
  "name": "Retired laptop 1",
  "cpu_cores": 4,
  "ram_gb": 8,
  "os": "Linux",
  "capabilities": ["dummy", "image_inference"],
  "baseline_power_w": 45
}
```

Response includes `node_id`, `node_secret`, `status` and
`heartbeat_interval_seconds`. Keep registration identity/credentials private and
separate for every agent. Registration with the same key updates that node.
The official agent advertises only workloads that pass actual runtime preflight;
the backend currently trusts enrollment-token holders' declared hardware/capabilities.

Heartbeat body for idle: `{"state":"IDLE","active_task_id":null}`.
Working: `{"state":"WORKING","active_task_id":"task-uuid","lease_token":"lease-uuid"}`.
Response: `{"acknowledged":true,"action":"NONE","lease_expires_at":"ISO time"}`;
expiry is omitted for idle. `CANCEL_TASK` means stop the local attempt. Heartbeats
renew a valid lease only up to the assignment's maximum deadline.

## Claim, execute, upload, complete

`GET /api/tasks/request` claims an eligible task atomically using PostgreSQL
`FOR UPDATE SKIP LOCKED`. Capability and reported RAM determine eligibility.
Repeated polling by the same worker recovers its existing active assignment:

```json
{
  "task_id": "task-uuid",
  "job_id": "job-uuid",
  "lease_token": "lease-uuid",
  "lease_expires_at": "ISO time",
  "attempt_deadline": "ISO time",
  "retry_count": 0,
  "payload": {
    "workload_type": "image_inference",
    "min_ram_gb": 2,
    "items": [{"key":"inputs/.../photo.jpg","name":"00000_photo.jpg","download_url":"temporary URL"}]
  }
}
```

Download input bytes; execute only the approved local workload. Obtain the upload
URL using `x-lease-token`, which returns `{upload_url,result_key}`. PUT result
JSON bytes to that URL with `Content-Type: application/json`. Default result size
limit: 5 MiB. Uploading alone does not complete a task.

Result artifact format:

```json
{
  "status": "SUCCESS",
  "itemsProcessed": 1,
  "itemsFailed": 0,
  "predictions": [{"image":"00000_photo.jpg","classId":281,"className":"tabby","confidence":0.85}],
  "errors": []
}
```

For mixed outcomes, status is `PARTIAL_FAILURE` and errors contain
`{"image":"exact assigned name","error":"description"}`. Counts must match
array lengths, every assigned name must occur exactly once across both arrays,
and unknown/duplicate/overlapping/missing names are rejected. Class ID must be
an integer 0–999; label must be nonempty and at most 200 characters; confidence
must be finite 0–1. At least one successful item is required. All-item failure
uses the `/fail` route. These checks establish structural correctness; they do
not prove that the predicted class is visually correct or calibrated.

After upload, completion body:

```json
{"lease_token":"lease-uuid","execution_time_ms":4500,"result_key":"outputs/job-uuid/task-uuid/lease-uuid/result.json"}
```

Backend validates ownership, active lease, artifact and exact input coverage
before accepting a task and creating its Metric in one database transaction.
It calculates estimated energy as `baseline_power_w * execution_time_ms / 3600000`;
the worker does not supply measured energy. Response status is `TASK_COMPLETED`,
`JOB_COMPLETED` or `JOB_PARTIAL_SUCCESS`. Repeating an already accepted completion
with the same worker/lease returns `already_completed:true` without another Metric.

Failure body: `{"lease_token":"lease-uuid","error":"description","retryable":true}`.
Response is `REQUEUED` if permitted by the retry budget, otherwise `FAILED`.
Stale/foreign attempts return 409 and cannot commit results.

## Dashboard and results

Dashboard snapshot contains `hardware` (total/active nodes, available cores/RAM),
`workloads` (completed task count, recent jobs, task counts), `environmental`
(`estimated_energy_wh`, summed `execution_time_ms`, `metric_type:"ESTIMATED"`)
and `nodes` (identity/name/status/hardware/capabilities/assumed power/heartbeat).
It is polled; no WebSocket or Redis is used. Available totals currently describe
active enrolled hardware, not free capacity measurements.

Downloaded job JSON contains `job_id`, `name`, job `status`, task counts,
`items_processed`, `items_failed`, `predictions`, `errors`, `metrics`.
Predictions/item errors include `task_id`; a terminal task failure contributes
its whole batch to `items_failed` and one task-level error. An in-progress
download is a partial snapshot, not a final report. Terminal job states are
`COMPLETED`, `PARTIAL_SUCCESS` and `FAILED`.
