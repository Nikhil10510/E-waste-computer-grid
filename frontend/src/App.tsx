import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Activity, Cpu, Zap, CheckCircle, Server, Plus, Download, RefreshCw, LogOut } from 'lucide-react';
import { downloadResults, fetchDashboardSync, submitNewJob, uploadInput } from './services/api';
import type { DashboardData, InputItem } from './services/api';
import './App.css';

function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('grid-admin-token') || '');
  const [tokenInput, setTokenInput] = useState('');
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [formError, setFormError] = useState('');
  const [notice, setNotice] = useState('');
  const [jobName, setJobName] = useState('');
  const [kind, setKind] = useState<'dummy' | 'image_inference'>('dummy');
  const [itemsCount, setItemsCount] = useState(20);
  const [chunkSize, setChunkSize] = useState(5);
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState('');
  const [refresh, setRefresh] = useState(0);
  const pending = useRef<{ fingerprint: string; key: string } | null>(null);
  const uploaded = useRef(new Map<File, InputItem>());

  useEffect(() => {
    if (!token) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const next = await fetchDashboardSync(token, AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]));
        if (!stopped) { setData(next); setError(''); }
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : 'Could not connect to the control plane');
      } finally {
        if (!stopped) timer = setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); controller.abort(); };
  }, [token, refresh]);

  const login = (event: FormEvent) => {
    event.preventDefault();
    const value = tokenInput.trim();
    sessionStorage.setItem('grid-admin-token', value);
    setData(null); setError(''); setToken(value);
  };
  const logout = () => { sessionStorage.removeItem('grid-admin-token'); setToken(''); setData(null); setError(''); };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true); setFormError(''); setNotice('');
    try {
      if (kind === 'image_inference' && !files.length) throw new Error('Select at least one image');
      let items: string[] | InputItem[];
      if (kind === 'dummy') {
        items = Array.from({ length: itemsCount }, (_, i) => `demo item ${i + 1}`);
      } else {
        const inputs: InputItem[] = [];
        for (const [index, file] of files.entries()) {
          setUploadProgress(`Uploading image ${index + 1} of ${files.length}…`);
          let input = uploaded.current.get(file);
          if (!input) { input = await uploadInput(file, token); uploaded.current.set(file, input); }
          inputs.push(input);
        }
        items = inputs;
      }
      const input = { name: jobName, workload_type: kind, items, chunk_size: chunkSize, min_ram_gb: kind === 'dummy' ? 0.25 : 2 };
      const fingerprint = JSON.stringify(input);
      if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint, key: crypto.randomUUID() };
      const job = await submitNewJob(input, token, pending.current.key);
      pending.current = null;
      setNotice(`${job.name} submitted: ${job.totalTasks} tasks. Workers will pick them up automatically.`);
      setJobName(''); setRefresh(value => value + 1);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Submission failed');
    } finally {
      setSubmitting(false); setUploadProgress('');
    }
  };

  if (!token) return (
    <main className="login-container glass-panel">
      <Cpu size={36} color="var(--accent-green)" />
      <h1>E-Waste Compute Grid</h1>
      <p>Connect to your grid to manage workers and workloads.</p>
      <form onSubmit={login} className="job-form">
        <label htmlFor="admin-token">Admin token</label>
        <input id="admin-token" type="password" required value={tokenInput} onChange={e => setTokenInput(e.target.value)} autoComplete="current-password" />
        <button className="submit-btn" type="submit">Connect to grid</button>
      </form>
      <small>Use the ADMIN_TOKEN configured for your control plane.</small>
    </main>
  );

  return (
    <main className="dashboard-container">
      <header className="dashboard-header">
        <div className="dashboard-title">
          <h1>E-Waste Compute Grid</h1>
          <p><span className={error ? 'connection-offline' : 'pulse-dot'} /> {error ? 'Connection interrupted' : data ? 'Connected to your grid' : 'Connecting…'}</p>
        </div>
        <button className="text-button" onClick={logout}><LogOut size={16} /> Disconnect</button>
      </header>
      {error && <div className="message error" role="alert">{error}. {data ? 'Showing the last received data.' : 'Check your token and backend connection.'} <button onClick={() => setRefresh(value => value + 1)}><RefreshCw size={14} /> Retry</button></div>}
      {!data && !error && <p role="status">Loading grid status…</p>}
      {data && <>
        <section className="stats-grid" aria-label="Grid metrics">
          <div className="glass-panel stat-card"><div className="stat-header"><Server size={22} /> Active nodes</div><div className="stat-value green">{data.hardware.active_nodes}<small> / {data.hardware.total_nodes}</small></div></div>
          <div className="glass-panel stat-card"><div className="stat-header"><Cpu size={22} /> Online compute</div><div className="stat-value blue">{data.hardware.available_cores}<small> cores</small></div></div>
          <div className="glass-panel stat-card"><div className="stat-header"><CheckCircle size={22} /> Tasks completed</div><div className="stat-value purple">{data.workloads.total_tasks_completed}</div></div>
          <div className="glass-panel stat-card"><div className="stat-header"><Zap size={22} /> Estimated compute energy</div><div className="stat-value energy">{data.environmental.estimated_energy_wh.toFixed(3)}<small> Wh</small></div><small>Hardware baseline × successful execution time</small></div>
        </section>
        <div className="content-grid">
          <div className="main-content">
            <section className="glass-panel">
              <h2 className="section-title"><Activity size={22} /> Worker nodes</h2>
              <div className="nodes-table-container"><table className="nodes-table">
                <thead><tr><th>Name</th><th>Status</th><th>CPU / RAM</th><th>Workloads</th></tr></thead>
                <tbody>{data.nodes.map(node => <tr key={node.id}>
                  <td title={node.id}>{node.name}</td><td><span className={`status-badge status-${node.status}`}>{node.status}</span></td>
                  <td>{node.cpuCores} cores / {node.ramGb.toFixed(1)} GB</td><td>{node.capabilities.join(', ')}</td>
                </tr>)}</tbody>
              </table></div>
              {!data.nodes.length && <p className="empty-state">No workers registered. Start a worker agent to contribute compute.</p>}
            </section>
            <section className="glass-panel jobs-section">
              <h2 className="section-title">Recent jobs</h2>
              {!data.workloads.recent_jobs.length && <p className="empty-state">Submit a demo or an image batch to get started.</p>}
              <div className="jobs-list">{data.workloads.recent_jobs.map(job => {
                const finished = job.completedTasks + job.failedTasks;
                const progress = job.totalTasks ? Math.round(100 * finished / job.totalTasks) : 0;
                return <article key={job.id} className="job-item">
                  <div className="job-header"><h3 className="job-name">{job.name}</h3><span className={`job-status ${job.status}`}>{job.status.replaceAll('_', ' ')}</span></div>
                  <div className="progress-bar" role="progressbar" aria-label={`${job.name} progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><div className="progress-fill" style={{ width: `${progress}%` }} /></div>
                  <p className="progress-text">{job.completedTasks} completed · {job.failedTasks} failed · {job.totalTasks} total tasks</p>
                  {['COMPLETED', 'PARTIAL_SUCCESS', 'FAILED'].includes(job.status) && <button className="text-button" onClick={() => void downloadResults(job.id, token).catch(e => setFormError(e.message))}><Download size={16} /> Download results</button>}
                </article>;
              })}</div>
            </section>
          </div>
          <section className="glass-panel submission-panel">
            <h2 className="section-title"><Plus size={22} /> New workload</h2>
            <form className="job-form" onSubmit={submit}>
              <fieldset disabled={submitting}>
                <div className="form-group"><label htmlFor="job-name">Job name</label><input id="job-name" required maxLength={200} value={jobName} onChange={e => setJobName(e.target.value)} placeholder="e.g. Campus image batch" /></div>
                <div className="form-group"><label htmlFor="workload-type">Workload</label><select id="workload-type" value={kind} onChange={e => setKind(e.target.value as typeof kind)}><option value="dummy">Pipeline demo</option><option value="image_inference">Image classification</option></select></div>
                {kind === 'dummy' ? <div className="form-group"><label htmlFor="item-count">Demo items</label><input id="item-count" type="number" min={1} max={10000} required value={itemsCount} onChange={e => setItemsCount(Number(e.target.value))} /></div> : <div className="form-group"><label htmlFor="images">Images (up to 20 MB each)</label><input id="images" type="file" multiple accept=".jpg,.jpeg,.png,.webp,.bmp" onChange={e => { setFiles(Array.from(e.target.files || [])); uploaded.current.clear(); }} /><small>{files.length} images selected</small></div>}
                <div className="form-group"><label htmlFor="chunk-size">Items per task</label><input id="chunk-size" type="number" min={1} max={100} required value={chunkSize} onChange={e => setChunkSize(Number(e.target.value))} /></div>
                <small>Estimated tasks: {Math.ceil((kind === 'dummy' ? itemsCount : files.length) / (chunkSize || 1))}</small>
                <button className="submit-btn" type="submit" disabled={!!error}>{submitting ? uploadProgress || 'Submitting…' : 'Submit workload'}</button>
              </fieldset>
            </form>
            {formError && <p className="message error" role="alert">{formError}</p>}
            {notice && <p className="message success" role="status">{notice}</p>}
            <p className="form-note">Image classification uses MobileNetV2 on worker CPUs. The pipeline demo uses deterministic sample results.</p>
          </section>
        </div>
      </>}
    </main>
  );
}
export default App;
