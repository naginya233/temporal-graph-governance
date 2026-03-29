import { expect, test } from "@playwright/test";

test("pipeline start/stop flow (local)", async ({ page }) => {
  test.skip(process.env.RUN_PIPELINE_FLOW !== "1", "Set RUN_PIPELINE_FLOW=1 to run this local flow.");

  await page.goto("/");
  await expect(page.locator("#progress-text")).toContainText("治理审阅");

  await page.locator("#run-max-frames").fill("1");
  await page.locator("#run-use-llm").uncheck();
  await page.locator("#run-gen-report").uncheck();

  await page.locator("#btn-run-start").click();
  await expect(page.locator("#runtime-status")).toContainText(/running|idle/, { timeout: 20_000 });

  const startState = await page.request.get("/api/pipeline/state");
  expect(startState.ok()).toBeTruthy();
  const startJson = await startState.json();

  if (startJson.running) {
    await page.locator("#btn-run-stop").click();
    await expect
      .poll(async () => {
        const res = await page.request.get("/api/pipeline/state");
        const json = await res.json();
        return json.running;
      }, { timeout: 25_000 })
      .toBe(false);
  }

  const endState = await page.request.get("/api/pipeline/state");
  expect(endState.ok()).toBeTruthy();
  const endJson = await endState.json();
  expect(endJson.running).toBe(false);
});
