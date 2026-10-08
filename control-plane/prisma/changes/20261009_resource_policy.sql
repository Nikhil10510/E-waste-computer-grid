-- Run once after the pairing upgrade, before the resource-policy backend.
BEGIN;
ALTER TABLE "Node"
  ADD COLUMN "cpuLimit" DOUBLE PRECISION,
  ADD COLUMN "memoryLimitGb" DOUBLE PRECISION,
  ADD COLUMN "paused" BOOLEAN NOT NULL DEFAULT false;
-- Existing approved desktop identities retain their previous default ceilings.
UPDATE "Node" SET "cpuLimit" = LEAST(2, "cpuCores"),
  "memoryLimitGb" = LEAST(2, "ramGb") WHERE "enrollmentMode" = 'paired';
COMMIT;
