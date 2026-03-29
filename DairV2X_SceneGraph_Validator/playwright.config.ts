import { defineConfig } from "@playwright/test";

const pythonCmd = process.env.PYTHON_CMD || "python";
const appPort = process.env.APP_PORT || "5000";
const appUrl = process.env.APP_URL || `http://127.0.0.1:${appPort}`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["line"], ["html", { open: "never" }]],
  use: {
    baseURL: appUrl,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${pythonCmd} app.py`,
    cwd: ".",
    url: appUrl,
    timeout: 120_000,
    reuseExistingServer: true,
  },
});
