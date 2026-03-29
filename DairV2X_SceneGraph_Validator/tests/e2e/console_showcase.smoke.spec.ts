import { expect, test } from "@playwright/test";

test("console and showcase smoke", async ({ page, context }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/DairV2X/);

  await page.getByRole("button", { name: "关系校对次功能" }).click();
  await expect(page.locator("#progress-text")).toContainText("关系校对");

  await page.getByRole("button", { name: "治理主功能" }).click();
  await expect(page.locator("#progress-text")).toContainText("治理审阅");

  await page.getByRole("button", { name: "设置路径" }).click();
  await expect(page.locator("#settings-modal.active")).toBeVisible();
  await page.click("#settings-modal button.btn-modal.secondary[onclick='closeSettings()']");
  await expect(page.locator("#settings-modal.active")).toHaveCount(0);

  await page.getByRole("button", { name: "外观" }).click();
  await page.locator("#ui-theme-select").selectOption("dark");
  await page.locator("#ui-performance-select").selectOption("rich");

  const prefs = await page.evaluate(() => {
    return JSON.parse(localStorage.getItem("dair_console_ui_prefs_v1") || "{}");
  });
  expect(prefs.theme).toBe("dark");
  expect(prefs.performanceMode).toBe("rich");

  const popupPromise = context.waitForEvent("page");
  await page.getByRole("link", { name: "展示页面" }).click();
  const showcase = await popupPromise;
  await showcase.waitForLoadState("domcontentloaded");

  await expect(showcase).toHaveTitle(/Showcase/);
  await expect(showcase.locator("#showcase-ui-state")).toContainText("rich");

  const beforeToggle = await showcase.locator("#showcase-ui-state").innerText();
  await showcase.locator("#toggle-theme-btn").click();
  await expect(showcase.locator("#showcase-ui-state")).not.toHaveText(beforeToggle);

  await showcase.getByRole("link", { name: "返回主界面" }).click();
  await expect(showcase).toHaveURL(/\/$/);
  await expect(showcase.locator("#progress-text")).toContainText("治理审阅");
});
