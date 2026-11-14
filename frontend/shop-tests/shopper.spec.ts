import { test, expect } from "@playwright/test";
test("scripted shopper journey: product choices, account links, order and explicit tracking", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/shop");
  await expect(
    page.getByRole("heading", { name: "Good clothes. An easy everyday." }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/results/shop-home.png",
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Everyday cotton shirt", exact: false })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Everyday cotton shirt", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Red", exact: true }).click();
  await page.getByRole("button", { name: "L", exact: true }).click();
  await expect(
    page.getByText("Selected: Red / L", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Red", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({
    path: "artifacts/results/shop-product.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "My account", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your orders", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/results/shop-orders.png",
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "View order ORD-1042 →", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Order details", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Blue / M · Quantity 1", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/results/shop-order.png",
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Track shipment →", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Parcel reported lost", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("SHIP-1042", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "artifacts/results/shop-tracking-lost.png",
    fullPage: true,
  });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Parcel reported lost", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
test("scripted incomplete tracking journey: no loss confirmation or replacement promise", async ({
  page,
  request,
}) => {
  await page.goto("/shop/account/orders");
  await page
    .getByRole("link", { name: "View order ORD-TRACKING →", exact: true })
    .click();
  await page
    .getByRole("link", { name: "Track shipment →", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Last reported in transit",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("There is no loss confirmation on this page.", {
      exact: false,
    }),
  ).toBeVisible();
  const detail = await (
    await request.get("/demo-shop/orders/ORD-TRACKING/tracking")
  ).json();
  expect(
    Date.now() - Date.parse(detail.shipment.carrier_observed_at),
  ).toBeGreaterThan(2 * 24 * 3600 * 1000);
  await expect(
    page.getByRole("button", { name: /approve|replace|checkout/i }),
  ).toHaveCount(0);
  await page.screenshot({
    path: "artifacts/results/shop-tracking-incomplete.png",
    fullPage: true,
  });
});
test("scripted staff handoff: old tracking stays unknown and source is a record, not a visited page", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("visitor");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.COMMERCE_STAFF_PASSWORD!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Order", { exact: true }).selectOption("ORD-TRACKING");
  await page.getByRole("button", { name: "Start review", exact: true }).click();
  await page
    .getByLabel("Shipment report", { exact: true })
    .fill(
      "Customer order ORD-TRACKING has an old tracking update. Please investigate without assuming loss.",
    );
  await expect(
    page.getByRole("button", { name: "Investigate shipment", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Investigate shipment", exact: true })
    .click();
  await expect(
    page.getByText("Investigation finished.", { exact: false }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page.getByText(
      "We need an up-to-date confirmation from the carrier that the parcel is lost.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByText("Evidence source", { exact: true }).first().click();
  await expect(
    page
      .getByText(
        "This rules run consulted database records, not browser pages.",
        { exact: true },
      )
      .first(),
  ).toBeVisible();
  await expect(
    page
      .getByRole("link", {
        name: "View corresponding customer page ↗",
        exact: true,
      })
      .first(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve replacement", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: "artifacts/results/staff-stale-record-evidence.png",
    fullPage: true,
  });
});
