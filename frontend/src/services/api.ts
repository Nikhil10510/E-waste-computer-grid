export const API_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');

export interface NodeData {
  id: string; name: string; status: string; cpuCores: number; ramGb: number;
  baselinePowerW: number; capabilities: string[]; lastHeartbeat: string;
  cpuLimit: number | null; memoryLimitGb: number | null; paused: boolean;
}
export interface JobData {
  id: string; name: string; status: string; totalTasks: number; completedTasks: number;
  failedTasks: number; createdAt: string;
  cancelledTasks: number; startedAt: string | null; completedAt: string | null;
}
export interface DashboardData {
  hardware: { active_nodes: number; total_nodes: number; available_cores: number; available_ram_gb: number };
  workloads: { total_tasks_completed: number; recent_jobs: JobData[]; task_counts: Record<string, number> };
  environmental: { estimated_energy_wh: number; metric_type: string };
  nodes: NodeData[];
}
export interface InputItem { key: string; name: string }
export interface PairingInvitation { pairing_id: string; state: string; expires_at: string; grid_name: string; worker_name: string }
export async function inviteWorker(code: string, token: string, signal?: AbortSignal): Promise<PairingInvitation> {
  return (await request('/pairing/invite', token, {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pairing_code: code }),
  })).json();
}
export interface JobInput {
  name: string; workload_type: 'dummy' | 'image_inference'; items: string[] | InputItem[];
  chunk_size: number; min_ram_gb: number;
}

async function request(path: string, token: string, options: RequestInit = {}) {
  const response = await fetch(API_URL + path, {
    ...options, signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(30000)]) : AbortSignal.timeout(30000),
    headers: { Authorization: `Bearer ${token}`, ...options.headers },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || `Request failed (${response.status})`);
  }
  return response;
}
export async function fetchDashboardSync(token: string, signal?: AbortSignal): Promise<DashboardData> {
  return (await request('/dashboard/sync', token, { signal })).json();
}
export async function uploadInput(file: File, token: string, signal?: AbortSignal): Promise<InputItem> {
  if (!file.size || file.size > 20 * 1024 * 1024) throw new Error(`${file.name}: image must be between 1 byte and 20 MB`);
  return (await request(`/inputs?name=${encodeURIComponent(file.name)}`, token, {
    method: 'POST', signal, headers: { 'Content-Type': 'application/octet-stream' }, body: file,
  })).json();
}
export async function submitNewJob(input: JobInput, token: string, requestKey: string, signal?: AbortSignal): Promise<JobData> {
  return (await request('/jobs', token, {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json', 'Idempotency-Key': requestKey }, body: JSON.stringify(input),
  })).json();
}
export async function downloadResults(id: string, token: string, signal?: AbortSignal) {
  const blob = await (await request(`/jobs/${id}/results`, token, { signal })).blob();
  signal?.throwIfAborted();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = `job-${id}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface AttemptData {
  number: number; worker_id: string; worker_name: string; status: string;
  assigned_at: string; finished_at: string | null; execution_time_ms: number | null; error: string | null;
}
export interface TaskData {
  id: string; job_id: string; status: string; worker_id: string | null; retry_count: number;
  assigned_at: string | null; completed_at: string | null; last_error: string | null;
  workload_type: string; item_count: number; min_ram_gb: number; execution_time_ms: number | null; attempts: AttemptData[];
}
export interface ResultItem {
  image: string; original_name: string; task_id: string; status: string; classId?: number; className?: string; confidence?: number; error?: string;
}
export interface JobDetailData {
  job: JobData; task_counts: Record<string, number>;
  items: { total: number; processed: number; failed: number; cancelled: number; pending: number };
  timing: { queue_wait_ms: number; elapsed_ms: number | null; cumulative_execution_ms: number; throughput_items_per_second: number | null };
  metrics: { contributing_workers: number; estimated_energy_wh: number; metric_type: string; scope: string };
  scheduling: { policy: string };
}
export const fetchJobs = async (token: string, page: number, signal?: AbortSignal): Promise<{ jobs: JobData[]; total: number; page: number; limit: number }> =>
  (await request(`/jobs?page=${page}&limit=10`, token, { signal })).json();
export const fetchJobDetail = async (id: string, token: string, signal?: AbortSignal): Promise<JobDetailData> =>
  (await request(`/jobs/${id}`, token, { signal })).json();
export const fetchJobTasks = async (id: string, token: string, page: number, signal?: AbortSignal): Promise<{ tasks: TaskData[]; total: number; page: number; limit: number }> =>
  (await request(`/jobs/${id}/tasks?page=${page}&limit=10`, token, { signal })).json();
export const fetchTaskDetail = async (id: string, token: string, page = 1, signal?: AbortSignal): Promise<{ task: TaskData; items: ResultItem[]; total_attempts: number; page: number; limit: number }> =>
  (await request(`/tasks/${id}?page=${page}&limit=10`, token, { signal })).json();
export const cancelJob = async (id: string, token: string, signal?: AbortSignal): Promise<JobData> =>
  (await request(`/jobs/${id}/cancel`, token, { method: 'POST', signal })).json();
