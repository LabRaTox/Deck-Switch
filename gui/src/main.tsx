import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { leiteLinksNachAussen } from "./externeLinks";
import "./i18n";
import "./styles.css";

leiteLinksNachAussen();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
