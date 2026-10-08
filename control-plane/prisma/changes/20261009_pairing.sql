-- Additive upgrade from the pre-pairing schema. Run once, before starting the
-- new backend. This is a reviewed SQL change, not a Prisma migration baseline.
BEGIN;
ALTER TABLE "Node"
  ADD COLUMN "enrollmentMode" TEXT NOT NULL DEFAULT 'legacy',
  ADD COLUMN "revokedAt" TIMESTAMP(3);

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
CREATE UNIQUE INDEX "PairingSession_codeHash_key" ON "PairingSession"("codeHash");
CREATE UNIQUE INDEX "PairingSession_nodeId_key" ON "PairingSession"("nodeId");
CREATE INDEX "PairingSession_expiresAt_idx" ON "PairingSession"("expiresAt");
ALTER TABLE "PairingSession" ADD CONSTRAINT "PairingSession_nodeId_fkey"
  FOREIGN KEY ("nodeId") REFERENCES "Node"("id") ON DELETE CASCADE ON UPDATE CASCADE;
COMMIT;
