import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installBackButton } from "./lib/backButton";
import "./index.css";

installBackButton(); // Android hardware back: see lib/backButton.ts (no-op on the web)

const container = document.getElementById("root");
if (!container) throw new Error("#root element not found");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>
);
