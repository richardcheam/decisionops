import React, { lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter/wght.css";
import "@fontsource-variable/inter-tight/wght.css";
import "@fontsource-variable/jetbrains-mono/wght.css";
import "./tokens.css";
import "./style.css";
import { CustomerPortal } from "./customer";
import { StaffWorkspace } from "./staff/workspace";

const Shop = lazy(() => import("./shop").then(({ Shop }) => ({ default: Shop })));
const path = window.location.pathname;
const isCustomer = path.startsWith("/customer");
const isShop = path.startsWith("/shop");
const requestedTheme = new URLSearchParams(window.location.search).get("theme");

if (!isShop) {
  const defaultTheme = isCustomer ? "light" : "dark";
  document.documentElement.dataset.theme =
    requestedTheme === "light" || requestedTheme === "dark" ? requestedTheme : defaultTheme;
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {isShop ? (
      <Suspense fallback={<p role="status">Loading shop…</p>}>
        <Shop />
      </Suspense>
    ) : isCustomer ? <CustomerPortal /> : <StaffWorkspace />}
  </React.StrictMode>,
);
