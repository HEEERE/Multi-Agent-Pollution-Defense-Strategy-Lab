import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { LanguageProvider } from "./i18n/context";
import "./styles.css";
import "@xyflow/react/dist/style.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </React.StrictMode>,
);
