# Grid dashboard

Owner: Chinmay. The dashboard polls the authenticated backend, displays nodes and
jobs, uploads input images, submits jobs and downloads terminal results.

From the repository root, in a separate terminal with the backend already running:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open the URL printed by Vite (normally `http://localhost:5173`). Enter the
backend's `ADMIN_TOKEN`. The default `/api` requests are proxied to
`http://localhost:8080`; set `API_PROXY_TARGET` before startup if the backend is
elsewhere. `VITE_API_URL` is an optional build-time override. A shared/public
deployment needs its own HTTPS hosting and authentication hardening.

Image classification is the default. Select genuine photos from
`workloads/test-data/demo`, use a job name and chunk size 5. Ten images produce
two tasks. Each file must be nonempty and no larger than 20 MiB. The form checks
the whole selection before starting uploads. A missing compatible worker leaves
the job queued, with an explanation in the form.

The pipeline demo mode creates deterministic synthetic results; use it for
orchestration checks, not classification evidence. Real results are class
labels/confidence, not object detection boxes. Energy is explicitly estimated.

```powershell
npm run build
npm run lint
```

Phase 1 verifies these checks. The browser upload/progress/download rehearsal on
a physical worker remains the Phase 2 acceptance gate; see `docs/PHASE_1_STATUS.md`.
