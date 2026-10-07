# E-Waste Compute Grid

A CPU batch-compute grid for trusted older computers, with a React dashboard, Node/Express controller, PostgreSQL coordination and Python workers. Supported workloads are MobileNetV2 image classification and a deterministic pipeline demo.

Start with the [complete project guide](docs/project_guide.md). It covers capabilities, architecture, changed code, setup, physical workers, dashboard operation, failure handling, tests and the hackathon demo. The printable copy is `output/pdf/E_Waste_Project_Guide.pdf`.

The [API contracts](docs/api_contracts.md) describe integration. `architecture_design.md` is the original design baseline; the guide identifies implementation differences.

Validation: 14 backend, 7 worker and 17 workload checks passed, plus both application builds and frontend lint. Docker execution, the complete Compose deployment, browser interactions and live AWS deployment remain unverified.
