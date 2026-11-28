import { expect, test, type BrowserContext } from "@playwright/test";

test("mocked Shopify pilot UI keeps proposal, approval and confirmation separate", async ({ browser }) => {
  const store = { id: "training-shop", name: "Training shop" };
  const order = { order_id: "gid://shopify/Order/12", name: "#12", lines: [{
    fulfillment_line_id: "gid://shopify/FulfillmentLineItem/34",
    title: "Blue tote", quantity: 1, eligible: true, reason: "Delivered and eligible",
  }] };
  const hash = "a".repeat(64);
  let connected = false;
  let imported = false;
  const row = {
    id: "pilot-return-1", order_id: order.order_id, fulfillment_line_id: order.lines[0].fulfillment_line_id,
    quantity: 1, status: "draft", reason: "Eligible", proposal_hash: null as string | null,
    external_return_id: null as string | null,
  };
  let filed = false;
  let confirmations = 0;

  async function configure(context: BrowserContext, role: "staff" | "approver") {
    let signedIn = false;
    const session = { email: role + "@example.test", stores: [{ ...store, role }] };
    const endpoint = "/pilot-api/shopify/" + store.id;
    await context.route("**/pilot-api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      const post = route.request().method() === "POST";
      const respond = (json: object, status = 200) => route.fulfill({ status, json });
      if (path === "/pilot-api/session") return signedIn ? respond(session) : respond({}, 401);
      if (["/pilot-api/login", "/pilot-api/invites/accept"].includes(path) && post) {
        signedIn = true;
        return respond(session);
      }
      if (!signedIn) return respond({}, 401);
      if (path === endpoint) return respond({ connected, shop: connected ? "training.myshopify.com" : null });
      if (path === endpoint + "/connect" && post) {
        expect(role).toBe("approver");
        expect(route.request().postDataJSON()).toEqual({ shop: "training.myshopify.com" });
        connected = true;
        return respond({ url: "/pilot?store_id=training-shop" });
      }
      if (path === endpoint + "/orders") return respond(imported ? [order] : []);
      if (path === endpoint + "/resync" && post) {
        imported = true;
        return respond([order]);
      }
      if (path === "/pilot-api/stores/training-shop/invites" && post) {
        expect(role).toBe("approver");
        expect(route.request().postDataJSON()).toEqual({ email: "staff@example.test", role: "staff" });
        return respond({ token: "mock-invitation" });
      }
      if (path === endpoint + "/cases") {
        if (!post) return respond(filed ? [row] : []);
        expect(role).toBe("staff");
        expect(route.request().postDataJSON()).toEqual({
          order_id: row.order_id, fulfillment_line_id: row.fulfillment_line_id,
        });
        filed = true;
        return respond(row);
      }
      if (path === endpoint + "/cases/" + row.id + "/propose" && post) {
        expect(role).toBe("staff");
        row.status = "proposed";
        row.proposal_hash = hash;
        return respond(row);
      }
      if (path === endpoint + "/cases/" + row.id + "/approve" && post) {
        expect(role).toBe("approver");
        expect(route.request().postDataJSON()).toEqual({ proposal_hash: hash });
        row.status = "approved";
        return respond(row);
      }
      if (path === endpoint + "/cases/" + row.id + "/confirm" && post) {
        expect(role).toBe("approver");
        expect(row.status).toBe("approved");
        expect(route.request().postDataJSON()).toEqual({ proposal_hash: hash });
        confirmations++;
        row.status = "verified";
        row.external_return_id = "gid://shopify/Return/56";
        return respond(row);
      }
      return respond({ detail: "Unexpected mocked request" }, 404);
    });
  }

  const managerContext = await browser.newContext();
  const staffContext = await browser.newContext();
  try {
    await configure(managerContext, "approver");
    await configure(staffContext, "staff");
    const manager = await managerContext.newPage();
    await manager.goto("/pilot");
    await manager.getByLabel("Email").fill("approver@example.test");
    await manager.getByLabel("Password").fill("fictional-test-password");
    await manager.getByRole("button", { name: "Sign in" }).click();
    await manager.getByLabel("Shopify domain").fill("training.myshopify.com");
    await manager.getByRole("button", { name: "Connect Shopify" }).click();
    await manager.getByRole("button", { name: "Resync test orders" }).click();
    await expect(manager.getByRole("heading", { name: "#12" })).toBeVisible();

    await manager.getByLabel("Staff email").fill("staff@example.test");
    await manager.getByRole("button", { name: "Create invitation" }).click();
    const invitation = manager.getByLabel("One-time invitation link");
    await expect(invitation).toHaveValue(/#invite=mock-invitation$/);
    const support = await staffContext.newPage();
    await support.goto(await invitation.inputValue());
    await support.getByLabel("Password").fill("fictional-agent-password");
    await support.getByRole("button", { name: "Accept invitation" }).click();
    await support.getByRole("button", { name: "Open return case for Blue tote" }).click();
    await support.getByRole("button", { name: "Submit return proposal" }).click();
    await expect(support.getByRole("status")).toHaveText("Proposed");
    await expect(support.getByRole("button", { name: "Approve return proposal" })).toHaveCount(0);

    await manager.getByRole("button", { name: "Refresh return cases" }).click();
    await manager.getByRole("button", { name: /pilot-return-1/ }).click();
    await manager.getByRole("button", { name: "Approve return proposal" }).click();
    await expect(manager.getByRole("dialog")).toContainText(row.fulfillment_line_id);
    await manager.getByRole("button", { name: "Confirm approval" }).click();
    await expect(manager.getByRole("status")).toHaveText("Approved");
    expect(confirmations).toBe(0);
    await manager.getByRole("button", { name: "Create Shopify return" }).click();
    await manager.getByRole("button", { name: "Confirm creation" }).click();
    await expect(manager.getByText("Verified Shopify return gid://shopify/Return/56")).toBeVisible();
    expect(confirmations).toBe(1);
  } finally {
    await managerContext.close();
    await staffContext.close();
  }
});
