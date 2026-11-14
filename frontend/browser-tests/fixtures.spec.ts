// Fixture scripts ONLY. Not imported by controller/transport or provider prompt.
import { test, expect } from "@playwright/test";
test("Site B tabs and disclosures reveal the carrier event only after opening parcel", async ({
  page,
}) => {
  await page.goto("http://127.0.0.1:8097/account");
  await expect(
    page.getByRole("tab", { name: "Purchases", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Loss confirmed", { exact: true })).toHaveCount(
    0,
  );
  await page.screenshot({
    path:
      process.env.BROWSER_ARTIFACT_DIR + "/screenshots/site-b-dashboard.png",
    fullPage: true,
  });
  await page.getByRole("tab", { name: "Purchases", exact: true }).click();
  await page
    .getByRole("link", { name: "Open receipt RC-9138", exact: true })
    .click();
  await expect(page.getByText("Loss confirmed", { exact: true })).toHaveCount(
    0,
  );
  await page.screenshot({
    path: process.env.BROWSER_ARTIFACT_DIR + "/screenshots/site-b-receipt.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Delivery", exact: true }).click();
  await expect(page.getByText("Loss confirmed", { exact: true })).toHaveCount(
    0,
  );
  await page
    .getByRole("button", { name: "Parcel BX-6942", exact: true })
    .click();
  await expect(
    page.getByRole("cell", { name: "Loss confirmed", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: process.env.BROWSER_ARTIFACT_DIR + "/screenshots/site-b-parcel.png",
    fullPage: true,
  });
});
