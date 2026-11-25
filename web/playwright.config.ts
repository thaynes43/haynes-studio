import * as os from "node:os";
import * as path from "node:path";

import { defineConfig, devices } from "@playwright/test";

// Contract section 14: one worker, serial, no retries that would hide a flake.
// Results go to the OS temp directory, never into the checkout.
export default defineConfig({
  testDir: "./e2e",
  testIgnore: "**/installed-playback.spec.ts",
  outputDir: path.join(os.tmpdir(), "haynes-studio-playwright"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  webServer: {
    command: "pnpm build && pnpm preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
