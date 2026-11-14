import React from "react";
import { createRoot } from "react-dom/client";
import { Shop } from "./shop";
import { SiteB } from "./site-b";
// Evaluation-only entry: no staff application import or session state.
createRoot(document.getElementById("root")!).render(
  window.location.pathname.startsWith("/shop") ? <Shop /> : <SiteB />,
);
