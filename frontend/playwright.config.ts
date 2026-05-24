import { defineConfig } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  adminToken,
  apiBaseUrl,
  backendPort,
  e2eHost,
  frontendBaseUrl,
  frontendPort,
  wsUrl,
} from './tests/e2eConfig';

const configDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(configDir, '..');
const pythonExecutable =
  process.env.PLAYWRIGHT_PYTHON ?? process.env.PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3');
const shellArg = (value: string) =>
  process.platform === 'win32'
    ? `"${value.replace(/"/g, '\\"')}"`
    : `'${value.replace(/'/g, "'\\''")}'`;

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  use: {
    baseURL: frontendBaseUrl,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command:
        `${shellArg(pythonExecutable)} -m uvicorn kyrgame.webapp:create_app --app-dir backend --factory --host ${e2eHost} --port ${backendPort}`,
      cwd: repoRoot,
      port: backendPort,
      reuseExistingServer: false,
      env: {
        DATABASE_URL: 'sqlite+pysqlite:///./.playwright-kyrgame.db',
        KYRGAME_ADMIN_TOKEN: adminToken,
        KYRGAME_RESET_ON_BOOT: '1',
        KYRGAME_RUN_MIGRATIONS: '0',
        KYRGAME_SEED_IF_EMPTY: '1',
        KYRGAME_TICK_SECONDS: '1000',
        KYRGAME_WS_COMMAND_RATE_LIMIT_MAX_EVENTS: '1000',
      },
    },
    {
      command: `npm run dev -- --host ${e2eHost} --port ${frontendPort}`,
      cwd: configDir,
      port: frontendPort,
      reuseExistingServer: false,
      env: {
        VITE_API_BASE_URL: apiBaseUrl,
        VITE_WS_URL: wsUrl,
      },
    },
  ],
});
