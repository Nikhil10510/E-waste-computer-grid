-- CreateTable
CREATE TABLE "Node" (
    "id" TEXT NOT NULL,
    "nodeSecret" TEXT NOT NULL,
    "registrationKey" TEXT,
    "status" TEXT NOT NULL DEFAULT 'ONLINE',
    "cpuCores" INTEGER NOT NULL,
    "name" TEXT NOT NULL DEFAULT 'Worker',
    "ramGb" DOUBLE PRECISION NOT NULL,
    "os" TEXT NOT NULL DEFAULT 'linux',
    "capabilities" JSONB NOT NULL,
    "baselinePowerW" DOUBLE PRECISION NOT NULL,
    "lastHeartbeat" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "enrollmentMode" TEXT NOT NULL DEFAULT 'legacy',
    "revokedAt" TIMESTAMP(3),
    "cpuLimit" DOUBLE PRECISION,
    "memoryLimitGb" DOUBLE PRECISION,
    "paused" BOOLEAN NOT NULL DEFAULT false,

    CONSTRAINT "Node_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PairingSession" (
    "id" TEXT NOT NULL,
    "codeHash" TEXT NOT NULL,
    "secretHash" TEXT NOT NULL,
    "state" TEXT NOT NULL DEFAULT 'WAITING',
    "hardware" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "invitedAt" TIMESTAMP(3),
    "decidedAt" TIMESTAMP(3),
    "nodeId" TEXT,

    CONSTRAINT "PairingSession_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Job" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'PENDING',
    "totalTasks" INTEGER NOT NULL,
    "completedTasks" INTEGER NOT NULL DEFAULT 0,
    "failedTasks" INTEGER NOT NULL DEFAULT 0,
    "requestKey" TEXT,
    "requestHash" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),

    CONSTRAINT "Job_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Task" (
    "id" TEXT NOT NULL,
    "jobId" TEXT NOT NULL,
    "nodeId" TEXT,
    "status" TEXT NOT NULL DEFAULT 'QUEUED',
    "payload" JSONB NOT NULL,
    "result" JSONB,
    "retryCount" INTEGER NOT NULL DEFAULT 0,
    "leaseExpiresAt" TIMESTAMP(3),
    "leaseToken" TEXT,
    "assignedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastError" TEXT,

    CONSTRAINT "Task_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Metric" (
    "id" TEXT NOT NULL,
    "nodeId" TEXT NOT NULL,
    "jobId" TEXT NOT NULL,
    "executionTimeMs" INTEGER NOT NULL,
    "energyWh" DOUBLE PRECISION NOT NULL,
    "timestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "taskId" TEXT,

    CONSTRAINT "Metric_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Node_registrationKey_key" ON "Node"("registrationKey");

-- CreateIndex
CREATE INDEX "Node_status_lastHeartbeat_idx" ON "Node"("status", "lastHeartbeat");

-- CreateIndex
CREATE UNIQUE INDEX "PairingSession_codeHash_key" ON "PairingSession"("codeHash");

-- CreateIndex
CREATE UNIQUE INDEX "PairingSession_nodeId_key" ON "PairingSession"("nodeId");

-- CreateIndex
CREATE INDEX "PairingSession_expiresAt_idx" ON "PairingSession"("expiresAt");

-- CreateIndex
CREATE UNIQUE INDEX "Job_requestKey_key" ON "Job"("requestKey");

-- CreateIndex
CREATE INDEX "Job_createdAt_idx" ON "Job"("createdAt");

-- CreateIndex
CREATE INDEX "Task_status_createdAt_idx" ON "Task"("status", "createdAt");

-- CreateIndex
CREATE INDEX "Task_status_leaseExpiresAt_idx" ON "Task"("status", "leaseExpiresAt");

-- CreateIndex
CREATE INDEX "Task_nodeId_status_idx" ON "Task"("nodeId", "status");

-- CreateIndex
CREATE INDEX "Task_jobId_status_idx" ON "Task"("jobId", "status");

-- CreateIndex
CREATE UNIQUE INDEX "Metric_taskId_key" ON "Metric"("taskId");

-- AddForeignKey
ALTER TABLE "PairingSession" ADD CONSTRAINT "PairingSession_nodeId_fkey" FOREIGN KEY ("nodeId") REFERENCES "Node"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Task" ADD CONSTRAINT "Task_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "Job"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Task" ADD CONSTRAINT "Task_nodeId_fkey" FOREIGN KEY ("nodeId") REFERENCES "Node"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Metric" ADD CONSTRAINT "Metric_nodeId_fkey" FOREIGN KEY ("nodeId") REFERENCES "Node"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Metric" ADD CONSTRAINT "Metric_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "Job"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Metric" ADD CONSTRAINT "Metric_taskId_fkey" FOREIGN KEY ("taskId") REFERENCES "Task"("id") ON DELETE SET NULL ON UPDATE CASCADE;
