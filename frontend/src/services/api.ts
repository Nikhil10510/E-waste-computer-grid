export const API_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');

export interface NodeData {
  id: string; name: string; status: string; cpuCores: number; ramGb: number;
  baselinePowerW: number; capabilities: string[]; lastHeartbeat: string;
}
export interface JobData {
  id: string; name: string; status: string; totalTasks: number; completedTasks: number;
  failedTasks: number; createdAt: string;
}
export interface DashboardData {
  hardware: { active_nodes: number; total_nodes: number; available_cores: number; available_ram_gb: number };
  workloads: { total_tasks_completed: number; recent_jobs: JobData[]; task_counts: Record<string, number> };
  environmental: { estimated_energy_wh: number; metric_type: string };
  nodes: NodeData[];
}
export interface InputItem { key: string; name: string }
export interface JobInput {
  name: string; workload_type: 'dummy' | 'image_inference'; items: string[] | InputItem[];
  chunk_size: number; min_ram_gb: number;
}

async function request(path: string, token: string, options: RequestInit = {}) {
  const response = await fetch(API_URL + path, {
    ...options, signal: options.signal || AbortSignal.timeout(30000),
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
export async function uploadInput(file: File, token: string): Promise<InputItem> {
  if (!file.size || file.size > 20 * 1024 * 1024) throw new Error(`${file.name}: image must be between 1 byte and 20 MB`);
  return (await request(`/inputs?name=${encodeURIComponent(file.name)}`, token, {
    method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
  })).json();
}
export async function submitNewJob(input: JobInput, token: string, requestKey: string): Promise<JobData> {
  return (await request('/jobs', token, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': requestKey }, body: JSON.stringify(input),
  })).json();
}
export async function downloadResults(id: string, token: string) {
  const blob = await (await request(`/jobs/${id}/results`, token)).blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = `job-${id}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
