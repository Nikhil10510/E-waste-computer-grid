import { app, prisma, sweep } from './app';
import { config } from './config';

async function start() {
  await prisma.$connect();
  await sweep();
  const server = app.listen(config.port, () => console.log(`Control plane listening on ${config.port}`));
  let sweeping = false;
  const timer = setInterval(async () => {
    if (sweeping) return;
    sweeping = true;
    try { await sweep(); } catch (error) { console.error('Recovery sweep failed:', error); }
    finally { sweeping = false; }
  }, config.sweepMs);
  let stopping = false;
  const stop = () => {
    if (stopping) return;
    stopping = true;
    clearInterval(timer);
    server.close(async () => { await prisma.$disconnect(); process.exit(0); });
    setTimeout(() => process.exit(1), 10_000).unref();
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}
start().catch(async error => { console.error('Startup failed:', error); await prisma.$disconnect(); process.exit(1); });
