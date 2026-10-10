import { useEffect, useRef, useState } from 'react';
import { cancelJob, downloadResults, fetchJobDetail, fetchJobs, fetchJobTasks, fetchTaskDetail } from './services/api';
import type { JobData, JobDetailData, ResultItem, TaskData } from './services/api';

const terminal = (status: string) => ['COMPLETED', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED'].includes(status);
const seconds = (ms: number | null) => ms === null ? 'Not started' : `${(ms / 1000).toFixed(2)} s`;

function Pager({ page, total, limit, change }: { page: number; total: number; limit: number; change: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / limit));
  return <nav className="job-actions" aria-label="Pagination">
    <button className="text-button" disabled={page <= 1} onClick={() => change(page - 1)}>Previous</button>
    <span>Page {page} of {pages} · {total} entries</span>
    <button className="text-button" disabled={page >= pages} onClick={() => change(page + 1)}>Next</button>
  </nav>;
}

function TaskDetail({ id, token }: { id: string; token: string }) {
  const [data, setData] = useState<{ task: TaskData; items: ResultItem[]; total_attempts: number } | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const reply = await fetchTaskDetail(id, token, page, controller.signal); if (!controller.signal.aborted) { setData(reply); setError(''); } }
      catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Task unavailable'); }
      finally { if (!controller.signal.aborted) timer = setTimeout(poll, 3000); }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, token, page]);
  return <section className="task-detail" aria-label="Batch results and assignment history">
    <h4>Batch {id.slice(0, 8)}: results and history</h4>
    {error && <p role="alert" className="message error">{error}. Displayed values may be stale.</p>}
    {!data && !error && <p role="status">Loading batch…</p>}
    {data && <>
      {!data.total_attempts && <p>This batch has no recorded assignment. Historical assignments from before this update are unavailable.</p>}
      <ol className="attempt-list">{data.task.attempts.map(a => <li key={a.number}>
        Attempt {a.number + 1}: <strong>{a.worker_name}</strong> · {a.status} · {new Date(a.assigned_at).toLocaleTimeString()}
        {a.finished_at && ` → ${new Date(a.finished_at).toLocaleTimeString()}`}
        {a.execution_time_ms !== null && ` · Compute ${seconds(a.execution_time_ms)}`}
        {a.error && <p className="batch-error">{a.error}</p>}
      </li>)}</ol>
      {data.total_attempts > 10 && <Pager page={page} total={data.total_attempts} limit={10} change={setPage} />}
      <div className="nodes-table-container"><table className="nodes-table result-table">
        <thead><tr><th>Input</th><th>Outcome</th><th>Prediction / error</th><th>Confidence</th></tr></thead>
        <tbody>{data.items.map(item => <tr key={item.image}>
          <td title={item.image}>{item.original_name}</td><td>{item.status}</td>
          <td>{item.className ?? item.error ?? 'Waiting for a result'}</td><td>{item.confidence === undefined ? '—' : `${(item.confidence * 100).toFixed(1)}%`}</td>
        </tr>)}</tbody>
      </table></div>
      <p className="form-note">Predictions are ImageNet object classes. A waste-category model has not been trained or installed.</p>
    </>}
  </section>;
}

function JobDetail({ id, token }: { id: string; token: string }) {
  const [summary, setSummary] = useState<JobDetailData | null>(null);
  const [tasks, setTasks] = useState<TaskData[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [busy, setBusy] = useState(false);
  const action = useRef<AbortController | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => () => action.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const [detail, batches] = await Promise.all([fetchJobDetail(id, token, controller.signal), fetchJobTasks(id, token, page, controller.signal)]);
        if (!controller.signal.aborted) { setSummary(detail); setTasks(batches.tasks); setTotal(batches.total); setError(''); }
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Job unavailable'); }
      finally { if (!controller.signal.aborted) timer = setTimeout(poll, 3000); }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, token, page, refresh]);
  const run = async (cancel: boolean) => {
    if (action.current) return;
    const controller = new AbortController(); action.current = controller; setBusy(true); setActionError('');
    try {
      if (cancel) await cancelJob(id, token, controller.signal); else await downloadResults(id, token, controller.signal);
      if (!controller.signal.aborted) { setConfirmCancel(false); setRefresh(n => n + 1); }
    } catch (e) { if (!controller.signal.aborted) setActionError(e instanceof Error ? e.message : 'Action failed. Retry safely.'); }
    finally { if (!controller.signal.aborted) { action.current = null; setBusy(false); } }
  };
  return <div className="job-detail">
    {error && <p className="message error" role="alert">{error}. Last received values may be stale.</p>}
    {!summary && !error && <p role="status">Loading job details…</p>}
    {summary && <>
      <dl className="job-metrics">
        <div><dt>Images / items</dt><dd>{summary.items.processed} processed · {summary.items.failed} failed · {summary.items.cancelled} cancelled · {summary.items.pending} waiting</dd></div>
        <div><dt>Job elapsed time</dt><dd>{seconds(summary.timing.elapsed_ms)}</dd></div>
        <div><dt>Cumulative accepted compute</dt><dd>{seconds(summary.timing.cumulative_execution_ms)}</dd></div>
        <div><dt>Queue wait</dt><dd>{seconds(summary.timing.queue_wait_ms)}</dd></div>
        <div><dt>Contributing workers</dt><dd>{summary.metrics.contributing_workers}</dd></div>
        <div><dt>Estimated accepted compute energy</dt><dd>{summary.metrics.estimated_energy_wh.toFixed(4)} Wh</dd></div>
      </dl>
      <p className="form-note">{summary.metrics.scope}. Job elapsed time includes retries and transfer waits. Cumulative compute sums accepted task durations and can exceed elapsed time during parallel execution.</p>
      <p className="form-note">Scheduling: {summary.scheduling.policy}.</p>
      {summary.items.pending > 0 && !tasks.some(t => t.status === 'ASSIGNED') && <p className="form-note">No assigned batch on this page. Check that workers are online, resumed, and meet the workload and approved RAM requirements.</p>}
      <div className="job-actions">
        {terminal(summary.job.status) && <button className="text-button" disabled={busy} onClick={() => void run(false)}>Download all results (JSON)</button>}
        {!terminal(summary.job.status) && <button className="text-button danger" disabled={busy} onClick={() => setConfirmCancel(true)}>Cancel unfinished work</button>}
      </div>
      {confirmCancel && !terminal(summary.job.status) && <div className="message" role="alert">
        Keep accepted results and cancel all unfinished batches? Workers stop when their next heartbeat detects cancellation; late results are rejected.
        <div className="job-actions"><button className="text-button danger" disabled={busy} onClick={() => void run(true)}>Confirm cancellation</button><button className="text-button" disabled={busy} onClick={() => setConfirmCancel(false)}>Keep running</button></div>
      </div>}
      {actionError && <p className="message error" role="alert">{actionError}</p>}
      <div className="nodes-table-container"><table className="nodes-table">
        <thead><tr><th>Batch</th><th>Items</th><th>State</th><th>Latest worker</th><th>Retries</th><th>Compute</th></tr></thead>
        <tbody>{tasks.map(task => <tr key={task.id}>
          <td><button className="batch-link" onClick={() => setSelected(selected === task.id ? null : task.id)}>{task.id.slice(0, 8)}</button></td>
          <td>{task.item_count}</td><td>{task.status}</td><td>{task.attempts[0]?.worker_name ?? (task.worker_id ? 'Historical worker' : 'Unassigned')}</td>
          <td>{task.retry_count}</td><td>{seconds(task.execution_time_ms)}</td>
        </tr>)}</tbody>
      </table></div>
      <Pager page={page} total={total} limit={10} change={n => { setPage(n); setSelected(null); }} />
      {selected && <TaskDetail key={selected} id={selected} token={token} />}
    </>}
  </div>;
}

export default function JobBrowser({ token, refresh }: { token: string; refresh: number }) {
  const [jobs, setJobs] = useState<JobData[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const reply = await fetchJobs(token, page, controller.signal);
        if (!controller.signal.aborted) { setJobs(reply.jobs); setTotal(reply.total); setError(''); setLoaded(true); }
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Jobs unavailable'); }
      finally { if (!controller.signal.aborted) timer = setTimeout(poll, 3000); }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [token, page, refresh]);
  return <section className="glass-panel jobs-section" aria-label="Jobs and results">
    <h2 className="section-title">Jobs and results</h2>
    {error && <p className="message error" role="alert">{error}. Displayed jobs may be stale.</p>}
    {!loaded && !error && <p role="status">Loading jobs…</p>}
    {loaded && !total && !error && <p className="empty-state">Submit an image batch or pipeline demo to get started.</p>}
    <div className="jobs-list">{jobs.map(job => {
      const finished = job.completedTasks + job.failedTasks + job.cancelledTasks;
      const progress = job.totalTasks ? Math.round(100 * finished / job.totalTasks) : 0;
      return <article key={job.id} className="job-item">
        <div className="job-header"><h3 className="job-name">{job.name}</h3><span className={`job-status ${job.status}`}>{job.status.replaceAll('_', ' ')}</span></div>
        <div className="progress-bar" role="progressbar" aria-label={`${job.name} terminal batch progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><div className="progress-fill" style={{ width: `${progress}%` }} /></div>
        <p className="progress-text">{job.completedTasks} completed · {job.failedTasks} failed · {job.cancelledTasks} cancelled · {job.totalTasks} batches</p>
        <button className="text-button" aria-expanded={selected === job.id} onClick={() => setSelected(selected === job.id ? null : job.id)}>{selected === job.id ? 'Hide details' : 'View batches and results'}</button>
        {selected === job.id && <JobDetail key={job.id} id={job.id} token={token} />}
      </article>;
    })}</div>
    {total > 10 && <Pager page={page} total={total} limit={10} change={n => { setPage(n); setSelected(null); }} />}
  </section>;
}
