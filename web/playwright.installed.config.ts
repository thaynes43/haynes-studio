import * as os from "node:os";
import * as path from "node:path";

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/installed-playback.spec.ts",
  outputDir: path.join(os.tmpdir(), "haynes-studio-installed-playwright"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    ...devices["Desktop Chrome"],
    viewport: { width: 400, height: 860 },
    serviceWorkers: "block",
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
