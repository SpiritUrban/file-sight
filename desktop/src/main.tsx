import React from "react";
import ReactDOM from "react-dom/client";

import App from "@/App";
import "@/index.css";
import { initLanguage } from "@/lib/i18n";
import { applyTheme, initialTheme } from "@/lib/preferences";
import { TauriWorkerClient } from "@/lib/tauriWorker";
import { useAppStore } from "@/stores/appStore";

// Before anything renders, and before the client is even built: the theme is
// a class on <html>, so applying it after mount would show a frame of the
// light theme on every start.
applyTheme(initialTheme());
initLanguage();

// The mock worker is a development aid only; a normal build never uses it.
async function makeClient() {
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK_WORKER === "1") {
    const { MockWorkerClient } = await import("@/lib/mockWorker");
    return new MockWorkerClient({ stepDelay: 120 });
  }
  return new TauriWorkerClient();
}

makeClient().then((client) => {
  useAppStore.getState().attachClient(client);
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});
