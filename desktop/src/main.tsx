import React from "react";
import ReactDOM from "react-dom/client";

import App from "@/App";
import "@/index.css";
import { TauriWorkerClient } from "@/lib/tauriWorker";
import { useAppStore } from "@/stores/appStore";

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
