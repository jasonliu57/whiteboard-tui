import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  timeout: 30000,
  fullyParallel: false,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:4173', browserName: 'chromium',
    viewport: { width: 1280, height: 800 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: { command: 'node scripts/serve.mjs', url: 'http://127.0.0.1:4173', reuseExistingServer: !process.env.CI }
});
