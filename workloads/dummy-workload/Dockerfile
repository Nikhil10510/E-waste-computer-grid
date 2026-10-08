# Dummy Workload — for pipeline testing without ML dependencies

FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY run_dummy.py .

VOLUME ["/data/input", "/data/output"]

CMD ["python", "run_dummy.py"]
