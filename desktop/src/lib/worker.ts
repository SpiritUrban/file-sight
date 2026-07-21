/**
 * The worker adapter: the only path from UI code to the Python core.
 *
 * `WorkerClient` is an interface so tests and UI development can swap in
 * a mock (lib/mockWorker.ts) without touching component code.
 */
import type { ValidationIssue, WorkerCommand, WorkerEvent } from "@/types";

export type EventHandler = (event: WorkerEvent) => void;

export interface WorkerClient {
  /** Ensure the backing process is up. Returns the executable used. */
  start(): Promise<string>;
  stop(): Promise<void>;
  /** Fire a command; events arrive through subscribe(). */
  send(
    requestId: string,
    command: WorkerCommand,
    payload?: Record<string, unknown>,
  ): Promise<void>;
  subscribe(handler: EventHandler): () => void;
  /** Convenience: send and resolve on the terminal event. */
  request<T = Record<string, unknown>>(
    command: WorkerCommand,
    payload?: Record<string, unknown>,
    onEvent?: EventHandler,
  ): Promise<T>;
}

export class WorkerRequestError extends Error {
  code: string;
  recoverable: boolean;
  /** Per-file reasons, so the UI can say what to fix rather than just "failed". */
  details: ValidationIssue[];

  constructor(
    code: string,
    message: string,
    recoverable = true,
    details: ValidationIssue[] = [],
  ) {
    super(message);
    this.name = "WorkerRequestError";
    this.code = code;
    this.recoverable = recoverable;
    this.details = details;
  }
}

/** Build the error carried by an `error` event. */
export function errorFromEvent(data: Record<string, unknown>): WorkerRequestError {
  return new WorkerRequestError(
    (data.code as string) ?? "UNKNOWN",
    (data.message as string) ?? "The worker reported an error.",
    (data.recoverable as boolean) ?? true,
    Array.isArray(data.details) ? (data.details as ValidationIssue[]) : [],
  );
}

export function newRequestId(): string {
  const globalCrypto = globalThis.crypto as Crypto | undefined;
  if (globalCrypto?.randomUUID) return globalCrypto.randomUUID();
  return `req-${Math.random().toString(36).slice(2)}-${Date.now()}`;
}

/**
 * Shared request/response plumbing: resolves on `completed`, rejects on
 * `error`, and forwards intermediate events to an optional listener.
 */
export abstract class BaseWorkerClient implements WorkerClient {
  private handlers = new Set<EventHandler>();

  abstract start(): Promise<string>;
  abstract stop(): Promise<void>;
  abstract send(
    requestId: string,
    command: WorkerCommand,
    payload?: Record<string, unknown>,
  ): Promise<void>;

  subscribe(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }

  protected dispatch(event: WorkerEvent): void {
    for (const handler of [...this.handlers]) {
      try {
        handler(event);
      } catch {
        // a broken listener must not stop the others
      }
    }
  }

  request<T = Record<string, unknown>>(
    command: WorkerCommand,
    payload: Record<string, unknown> = {},
    onEvent?: EventHandler,
  ): Promise<T> {
    const requestId = newRequestId();
    return new Promise<T>((resolve, reject) => {
      const unsubscribe = this.subscribe((event) => {
        if (event.request_id !== requestId) return;
        onEvent?.(event);
        if (event.event === "completed") {
          unsubscribe();
          resolve(event.data as T);
        } else if (event.event === "error") {
          unsubscribe();
          reject(errorFromEvent(event.data));
        }
      });
      this.send(requestId, command, payload).catch((error: unknown) => {
        unsubscribe();
        reject(
          error instanceof Error ? error : new Error(String(error)),
        );
      });
    });
  }

  /** Start a long operation, exposing its id so it can be cancelled. */
  startOperation<T = Record<string, unknown>>(
    command: WorkerCommand,
    payload: Record<string, unknown>,
    onEvent: EventHandler,
  ): { requestId: string; promise: Promise<T> } {
    const requestId = newRequestId();
    const promise = new Promise<T>((resolve, reject) => {
      const unsubscribe = this.subscribe((event) => {
        if (event.request_id !== requestId) return;
        onEvent(event);
        if (event.event === "completed") {
          unsubscribe();
          resolve(event.data as T);
        } else if (event.event === "error") {
          unsubscribe();
          reject(errorFromEvent(event.data));
        }
      });
      this.send(requestId, command, payload).catch((error: unknown) => {
        unsubscribe();
        reject(error instanceof Error ? error : new Error(String(error)));
      });
    });
    return { requestId, promise };
  }
}
