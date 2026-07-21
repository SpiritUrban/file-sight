/**
 * Production worker client: talks to the Rust shell, which owns the
 * Python process. The frontend never names a program to execute.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

import { safeParse, workerEventSchema } from "@/lib/schemas";
import { BaseWorkerClient } from "@/lib/worker";
import type { WorkerCommand, WorkerEvent } from "@/types";

export class TauriWorkerClient extends BaseWorkerClient {
  private unlisten: UnlistenFn | null = null;
  private started = false;

  async start(): Promise<string> {
    if (!this.unlisten) {
      this.unlisten = await listen<unknown>("worker-event", (message) => {
        const parsed = safeParse<WorkerEvent>(workerEventSchema, message.payload);
        if (!parsed.ok) {
          // Surface, don't crash: the UI shows a recoverable error.
          this.dispatch({
            request_id: "",
            event: "error",
            data: {
              code: "WORKER_PROTOCOL_ERROR",
              message: `Unreadable worker event (${parsed.error}).`,
              recoverable: true,
            },
          });
          return;
        }
        this.dispatch(parsed.value);
      });
    }
    const executable = await invoke<string>("start_worker");
    this.started = true;
    return executable;
  }

  async stop(): Promise<void> {
    if (this.started) {
      await invoke("stop_worker");
      this.started = false;
    }
    if (this.unlisten) {
      this.unlisten();
      this.unlisten = null;
    }
  }

  async send(
    requestId: string,
    command: WorkerCommand,
    payload: Record<string, unknown> = {},
  ): Promise<void> {
    await invoke("send_worker_command", {
      requestId,
      command,
      payload,
    });
  }
}
