# Current API contracts

Base path: `/api`. JSON requests use `Content-Type: application/json` except binary uploads. Errors return `{ "error": "message" }`. The executable reference is `control-plane/src/app.ts` and its integration tests. See [the project guide](project_guide.md) for setup and operation.

## Authentication

- Admin: `Authorization: Bearer <ADMIN_TOKEN>`.
- Enrollment: `Authorization: Bearer <ENROLLMENT_TOKEN>`.
- Worker: `Authorization: Bearer <node_secret>` and `x-node-id: <node_id>`.
- Storage transfers: use the returned signed URL unchanged.

## Admin endpoints

| Method and route | Contract |
| --- | --- |
| GET /health | Public database health check; returns status and storage driver |
| GET /dashboard/sync | Admin; hardware, workloads, environmental estimates and nodes; latest 50 jobs |
| POST /inputs?name=photo.jpg | Admin; raw application/octet-stream body; default 20 MiB; returns key and name |
| POST /jobs | Admin and Idempotency-Key header; body example below |
| GET /jobs/:job_id/results | Admin; current job status, task/item counts, predictions, errors and estimated metrics |

Supported image extensions: JPG, JPEG, PNG, WebP and BMP. Upload each image before submitting the returned objects in a job.

```json
{
  "name": "Photo batch",
  "workload_type": "image_inference",
  "items": [{ "key": "inputs/<uuid>/photo.jpg", "name": "photo.jpg" }],
  "chunk_size": 5,
  "min_ram_gb": 2
}
```

For dummy jobs, use `workload_type: "dummy"` and strings in items, such as `["demo one", "demo two"]`. Accepts 1-10000 items and integer chunk size 1-100 (default 10). RAM defaults to 2 GB for inference, 0.25 GB for dummy. Repeating a submission key and identical content returns the same job; changing content with that key returns 409. Terminal job states: COMPLETED, PARTIAL_SUCCESS, FAILED.

## Worker enrollment

POST /nodes/register with the enrollment token:

```json
{
  "registration_key": "persistent-worker-generated-uuid",
  "name": "lab-pc-1",
  "cpu_cores": 4,
  "ram_gb": 7.8,
  "os": "Windows",
  "capabilities": ["dummy", "image_inference"],
  "baseline_power_w": 45
}
```

Returns node_id, node_secret, status and heartbeat_interval_seconds. Persist credentials and registration_key; reusing the key preserves node identity.

## Worker lifecycle

All following routes require worker authentication.

POST /nodes/:node_id/heartbeat takes state (IDLE or WORKING), active_task_id (null when idle), and lease_token when working. Returns acknowledged, action (NONE or CANCEL_TASK) and lease_expires_at for a valid active attempt. An expired lease cannot be revived; extensions stop at the attempt deadline.

GET /tasks/request returns 204 when no compatible work exists. Otherwise returns task_id, job_id, lease_token, lease_expires_at, attempt_deadline, retry_count and payload. Payload includes workload_type, min_ram_gb and items. Image items contain signed download URLs; dummy items contain content. Resolve relative URLs against the controller URL. Repeated polling returns the existing active assignment.

GET /tasks/:task_id/upload-url also requires x-lease-token. Returns upload_url and result_key. PUT the result to this URL as application/json, default maximum 5 MiB.

Result JSON contains itemsProcessed, itemsFailed, predictions and errors. Counts must cover all assigned items, with at least one successful item. Predictions require unique image names; confidence, if supplied, is between 0 and 1. Entirely failed execution uses the failure endpoint.

POST /tasks/:task_id/complete:

```json
{
  "lease_token": "<current-attempt-token>",
  "result_key": "<returned-result-key>",
  "execution_time_ms": 1200
}
```

Upload first. The server checks ownership, lease and output, and records a single metric. Duplicate completion of the accepted attempt is idempotent. Stale attempt tokens return 409.

POST /tasks/:task_id/fail:

```json
{
  "lease_token": "<current-attempt-token>",
  "error": "Workload timed out",
  "retryable": true
}
```

Returns status REQUEUED or FAILED. The default permits three retries after the initial attempt. Duplicate failure reporting is idempotent until a new attempt is assigned.

## Storage and errors

GET/PUT /storage are the signed local-adapter routes. Use returned URLs instead of constructing them. S3 mode returns S3 presigned URLs.

Common HTTP errors: 400 invalid input, 401 invalid credentials, 403 node mismatch, 404 missing resource, 409 stale attempt or idempotency conflict, 413 oversized request, 500 internal failure. A 204 task response means no work. Retry transient failures with backoff while respecting the lease deadline.

