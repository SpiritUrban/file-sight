import { beforeEach, describe, expect, it } from "vitest";

import { MockWorkerClient, mockReport, MOCK_ENTRIES } from "@/lib/mockWorker";
import {
  defaultScanOptions,
  emptyProgress,
  isBusy,
  useAppStore,
} from "@/stores/appStore";

function freshStore(client = new MockWorkerClient()) {
  useAppStore.setState({
    client,
    uiState: "idle",
    report: null,
    reportPath: null,
    logPath: null,
    dirty: false,
    errorMessage: null,
    errorDetail: null,
    validation: null,
    plan: null,
    renameResult: null,
    undoResult: null,
    selectedPath: null,
    filter: "all",
    categoryFilter: "all",
    search: "",
    sortKey: "original_name",
    sortAsc: true,
    activeRequestId: null,
    settings: null,
    environment: null,
    options: { ...defaultScanOptions, directory: "C:\\Photos" },
    progress: { ...emptyProgress },
  });
  return client;
}

describe("bootstrap", () => {
  beforeEach(() => freshStore());

  it("loads environment and profiles", async () => {
    await useAppStore.getState().bootstrap();
    const state = useAppStore.getState();
    expect(state.environment?.python.ok).toBe(true);
    expect(state.profiles.map((p) => p.name)).toContain("photos");
    expect(state.workerExecutable).toBe("C:\\mock\\python.exe");
  });

  it("reports an error when the worker cannot start", async () => {
    const client = new MockWorkerClient();
    client.start = async () => {
      throw new Error("Python not found");
    };
    freshStore(client);
    await useAppStore.getState().bootstrap();
    expect(useAppStore.getState().uiState).toBe("error");
    expect(useAppStore.getState().errorMessage).toContain("Python not found");
  });
});

describe("scanning", () => {
  beforeEach(() => freshStore());

  it("moves through progress events to a ready report", async () => {
    await useAppStore.getState().startScan();
    const state = useAppStore.getState();
    expect(state.uiState).toBe("report_ready");
    expect(state.report?.files).toHaveLength(MOCK_ENTRIES.length);
    expect(state.progress.total).toBe(MOCK_ENTRIES.length);
    expect(state.progress.completed).toBe(MOCK_ENTRIES.length);
    expect(state.progress.succeeded).toBe(3);
    expect(state.progress.failed).toBe(1);
  });

  it("refuses to scan without a folder", async () => {
    useAppStore.getState().setDirectory("");
    await useAppStore.getState().startScan();
    expect(useAppStore.getState().uiState).toBe("error");
    expect(useAppStore.getState().errorMessage).toMatch(/choose a folder/i);
  });

  it("surfaces a worker error without losing the UI", async () => {
    const client = new MockWorkerClient({
      scanError: { code: "MODEL_LOAD_FAILED", message: "Unable to load the model." },
    });
    freshStore(client);
    await useAppStore.getState().startScan();
    const state = useAppStore.getState();
    expect(state.uiState).toBe("error");
    expect(state.errorMessage).toContain("Unable to load the model");
    expect(state.errorDetail).toBe("MODEL_LOAD_FAILED");
  });

  it("handles an unreadable event as a recoverable error", async () => {
    freshStore(new MockWorkerClient({ emitGarbage: true }));
    await useAppStore.getState().startScan();
    expect(useAppStore.getState().uiState).toBe("error");
    expect(useAppStore.getState().errorDetail).toBe("WORKER_PROTOCOL_ERROR");
  });

  it("can start a new scan after a previous one finished", async () => {
    await useAppStore.getState().startScan();
    expect(useAppStore.getState().uiState).toBe("report_ready");
    await useAppStore.getState().startScan();
    expect(useAppStore.getState().uiState).toBe("report_ready");
  });

  it("blocks a second concurrent scan", async () => {
    const client = freshStore(new MockWorkerClient({ stepDelay: 5 }));
    const first = useAppStore.getState().startScan();
    await useAppStore.getState().startScan(); // ignored while busy
    await first;
    const scans = client.sent.filter((s) => s.command === "scan");
    expect(scans).toHaveLength(1);
  });
});

describe("cancellation", () => {
  it("stops an in-flight scan and keeps partial results", async () => {
    const client = freshStore(new MockWorkerClient({ stepDelay: 10 }));
    const scan = useAppStore.getState().startScan();
    // wait until the scan is actually running
    await new Promise((resolve) => setTimeout(resolve, 25));
    await useAppStore.getState().cancelScan();
    await scan;

    expect(client.sent.some((s) => s.command === "cancel")).toBe(true);
    const state = useAppStore.getState();
    expect(state.uiState).toBe("report_ready");
    expect(state.progress.phase).toBe("Cancelled");
    expect(state.report!.files.length).toBeLessThan(MOCK_ENTRIES.length);
  });

  it("allows a fresh scan after cancelling", async () => {
    freshStore(new MockWorkerClient({ stepDelay: 5 }));
    const scan = useAppStore.getState().startScan();
    await new Promise((resolve) => setTimeout(resolve, 12));
    await useAppStore.getState().cancelScan();
    await scan;

    freshStore(new MockWorkerClient());
    await useAppStore.getState().startScan();
    expect(useAppStore.getState().report?.files).toHaveLength(MOCK_ENTRIES.length);
  });
});

describe("editing the report", () => {
  beforeEach(async () => {
    freshStore();
    await useAppStore.getState().startScan();
  });

  it("marks the report dirty when a name changes", () => {
    const path = MOCK_ENTRIES[0].original_path;
    expect(useAppStore.getState().dirty).toBe(false);
    useAppStore.getState().setSuggestedName(path, "new-name.jpg");
    const state = useAppStore.getState();
    expect(state.dirty).toBe(true);
    expect(
      state.report!.files.find((f) => f.original_path === path)!.suggested_name,
    ).toBe("new-name.jpg");
  });

  it("reports inline validation errors", () => {
    const path = MOCK_ENTRIES[0].original_path;
    useAppStore.getState().setSuggestedName(path, "bad:name.jpg");
    expect(useAppStore.getState().entryErrors().get(path)).toMatch(/does not allow/i);

    useAppStore.getState().setSuggestedName(path, "");
    expect(useAppStore.getState().entryErrors().get(path)).toMatch(/empty/i);

    useAppStore.getState().setSuggestedName(path, "sub\\dir.jpg");
    expect(useAppStore.getState().entryErrors().get(path)).toMatch(/not a path/i);

    useAppStore.getState().setSuggestedName(path, "photo.png");
    expect(useAppStore.getState().entryErrors().get(path)).toMatch(/extension/i);

    useAppStore.getState().setSuggestedName(path, "CON.jpg");
    expect(useAppStore.getState().entryErrors().get(path)).toMatch(/reserve/i);

    useAppStore.getState().setSuggestedName(path, "fine.jpg");
    expect(useAppStore.getState().entryErrors().get(path)).toBeUndefined();
  });

  it("detects duplicate targets between enabled files", () => {
    const [first, second] = MOCK_ENTRIES;
    useAppStore.getState().setSuggestedName(first.original_path, "same.jpg");
    useAppStore.getState().setSuggestedName(second.original_path, "same.jpg");
    const errors = useAppStore.getState().entryErrors();
    expect(errors.get(first.original_path)).toMatch(/already targets/i);
    expect(errors.get(second.original_path)).toMatch(/already targets/i);
  });

  it("toggles rename_enabled per file", () => {
    const path = MOCK_ENTRIES[0].original_path;
    useAppStore.getState().setRenameEnabled(path, false);
    expect(
      useAppStore.getState().report!.files.find((f) => f.original_path === path)!
        .rename_enabled,
    ).toBe(false);
  });

  it("enables and disables all visible files but never failed ones", () => {
    useAppStore.getState().setVisibleEnabled(false);
    expect(
      useAppStore.getState().report!.files.every((f) => !f.rename_enabled),
    ).toBe(true);

    useAppStore.getState().setVisibleEnabled(true);
    const files = useAppStore.getState().report!.files;
    expect(files.filter((f) => f.status === "success").every((f) => f.rename_enabled)).toBe(true);
    expect(files.find((f) => f.status === "failed")!.rename_enabled).toBe(false);
  });

  it("resets names back to the generated values", () => {
    const path = MOCK_ENTRIES[0].original_path;
    useAppStore.getState().setSuggestedName(path, "scribble.jpg");
    useAppStore.getState().resetSuggestedNames();
    expect(
      useAppStore.getState().report!.files.find((f) => f.original_path === path)!
        .suggested_name,
    ).toBe(MOCK_ENTRIES[0].naming!.suggested_name);
  });

  it("saves and clears the dirty flag", async () => {
    useAppStore.getState().setSuggestedName(MOCK_ENTRIES[0].original_path, "x.jpg");
    const path = await useAppStore.getState().saveReport();
    expect(path).toBeTruthy();
    expect(useAppStore.getState().dirty).toBe(false);
  });
});

describe("filters, search and sorting", () => {
  beforeEach(async () => {
    freshStore();
    await useAppStore.getState().startScan();
  });

  it("filters by media type and status", () => {
    useAppStore.getState().setFilter("videos");
    expect(useAppStore.getState().visibleEntries()).toHaveLength(1);

    useAppStore.getState().setFilter("failed");
    expect(useAppStore.getState().visibleEntries()[0].status).toBe("failed");

    useAppStore.getState().setFilter("images");
    expect(
      useAppStore.getState().visibleEntries().every((f) => f.media_type === "image"),
    ).toBe(true);
  });

  it("filters by category", () => {
    useAppStore.getState().setCategoryFilter("people");
    const visible = useAppStore.getState().visibleEntries();
    expect(visible).toHaveLength(1);
    expect(visible[0].classification?.category).toBe("people");
  });

  it("searches names, captions and categories", () => {
    useAppStore.getState().setSearch("woman");
    expect(useAppStore.getState().visibleEntries()).toHaveLength(1);

    useAppStore.getState().setSearch("clip.mp4");
    expect(useAppStore.getState().visibleEntries()[0].media_type).toBe("video");

    useAppStore.getState().setSearch("zzz-nothing");
    expect(useAppStore.getState().visibleEntries()).toHaveLength(0);
  });

  it("sorts and reverses on repeat", () => {
    useAppStore.getState().setSort("original_name");
    const ascending = useAppStore.getState().visibleEntries().map((f) => f.original_name);
    useAppStore.getState().setSort("original_name");
    const descending = useAppStore.getState().visibleEntries().map((f) => f.original_name);
    expect(descending).toEqual([...ascending].reverse());
  });

  it("handles a thousand rows quickly", async () => {
    const many = Array.from({ length: 1000 }, (_, index) => ({
      ...MOCK_ENTRIES[0],
      original_path: `C:\\Photos\\IMG_${index}.jpg`,
      original_name: `IMG_${index}.jpg`,
      suggested_name: `name-${index}.jpg`,
    }));
    useAppStore.setState({ report: mockReport(many) });
    const started = performance.now();
    const visible = useAppStore.getState().visibleEntries();
    expect(visible).toHaveLength(1000);
    expect(performance.now() - started).toBeLessThan(500);
  });
});

describe("validate, plan, rename and undo", () => {
  beforeEach(async () => {
    freshStore();
    await useAppStore.getState().startScan();
  });

  it("validates through the worker", async () => {
    const result = await useAppStore.getState().validateReport();
    expect(result?.valid).toBe(true);
    expect(result?.ready).toBe(3);
    expect(useAppStore.getState().uiState).toBe("report_ready");
  });

  it("builds a dry-run plan without changing anything", async () => {
    const client = useAppStore.getState().client as MockWorkerClient;
    const plan = await useAppStore.getState().buildPlan();
    expect(plan?.rename_count).toBe(3);
    expect(useAppStore.getState().uiState).toBe("rename_preview");
    expect(client.sent.some((s) => s.command === "apply_rename")).toBe(false);
  });

  it("applies a rename and records the log path", async () => {
    const result = await useAppStore.getState().applyRename();
    expect(result?.status).toBe("completed");
    expect(result?.renamed).toBe(3);
    const state = useAppStore.getState();
    expect(state.uiState).toBe("rename_completed");
    expect(state.logPath).toContain("filesight-rename-log");
  });

  it("shows a partial failure as failure, not success", async () => {
    freshStore(new MockWorkerClient({ partialRename: true }));
    await useAppStore.getState().startScan();
    const result = await useAppStore.getState().applyRename();
    expect(result?.status).toBe("partially_rolled_back");
    expect(result?.all_restored).toBe(false);
    expect(useAppStore.getState().uiState).toBe("rename_failed");
  });

  it("previews and performs undo", async () => {
    await useAppStore.getState().applyRename();
    const preview = await useAppStore.getState().undoLast(undefined, true);
    expect(preview?.status).toBe("dry_run");

    const result = await useAppStore.getState().undoLast(undefined, false);
    expect(result?.status).toBe("undone");
    expect(result?.restored).toBe(3);
    expect(useAppStore.getState().uiState).toBe("report_ready");
  });

  it("regenerates names from a different profile without a model", async () => {
    const client = useAppStore.getState().client as MockWorkerClient;
    await useAppStore.getState().regenerateNames("compact");
    const state = useAppStore.getState();
    expect(state.dirty).toBe(true);
    expect(state.report!.files[0].suggested_name).toMatch(/^compact-/);
    expect(client.sent.some((s) => s.command === "scan" && s.payload.profile === "compact")).toBe(false);
  });
});

describe("live analysis stage", () => {
  it("tracks the current file, its preview and per-file steps", async () => {
    const client = freshStore(new MockWorkerClient({ stepDelay: 5 }));
    const seen: Array<{ file: string | null; thumb: string | null; step: string | null }> = [];
    const unsubscribe = useAppStore.subscribe((state) => {
      seen.push({
        file: state.progress.currentFile,
        thumb: state.progress.currentThumbnail,
        step: state.progress.stepLabel,
      });
    });

    await useAppStore.getState().startScan();
    unsubscribe();

    // every scanned file appeared as "current" at some point, with a preview
    const files = seen.map((s) => s.file).filter(Boolean);
    expect(files).toContain("IMG_0001.jpg");
    expect(files).toContain("clip.mp4");
    expect(seen.some((s) => s.thumb?.includes("IMG_0001.jpg"))).toBe(true);
    // the video reported a sub-step
    expect(seen.some((s) => s.step === "Analyzing frame")).toBe(true);
    expect(client.sent.some((s) => s.command === "scan")).toBe(true);
  });

  it("records each result as it completes, newest first", async () => {
    freshStore();
    await useAppStore.getState().startScan();
    const { recent, lastResult } = useAppStore.getState().progress;

    expect(recent.length).toBeGreaterThan(1);
    expect(recent[0].name).toBe("broken.png"); // last file processed
    expect(recent[0].status).toBe("failed");
    expect(recent[0].error).toContain("cannot identify");

    const dog = recent.find((r) => r.name === "IMG_0001.jpg");
    expect(dog?.suggestedName).toBe("animals-black-dog-running.jpg");
    expect(dog?.category).toBe("animals");
    expect(dog?.caption).toContain("black dog");
    expect(lastResult?.name).toBe("broken.png");
  });

  it("never carries a previous file's result into the next one", async () => {
    freshStore(new MockWorkerClient({ stepDelay: 2 }));
    const snapshots: Array<{ file: string | null; result: string | null }> = [];
    const unsubscribe = useAppStore.subscribe((state) =>
      snapshots.push({
        file: state.progress.currentFile,
        result: state.progress.lastResult?.name ?? null,
      }),
    );
    await useAppStore.getState().startScan();
    unsubscribe();

    // whenever a result is shown it belongs to the file being displayed,
    // never to an earlier one
    for (const snap of snapshots) {
      if (snap.result) expect(snap.result).toBe(snap.file);
    }
  });

  it("leaves the model-loading state as soon as a file starts", async () => {
    freshStore(new MockWorkerClient({ stepDelay: 2 }));
    const states: string[] = [];
    const unsubscribe = useAppStore.subscribe((s) => states.push(s.uiState));
    await useAppStore.getState().startScan();
    unsubscribe();

    // the mock emits "Loading model" and then goes straight to files, with
    // no further phase event — the UI must still move on
    expect(states).toContain("loading_model");
    expect(states).toContain("analyzing");
    expect(states.lastIndexOf("analyzing")).toBeGreaterThan(
      states.indexOf("loading_model"),
    );
  });
});

describe("configured tool paths", () => {
  it("sends the FFmpeg paths with every scan", async () => {
    const client = freshStore();
    useAppStore.setState({
      settings: {
        python_path: null,
        ffmpeg_path: "C:\\tools\\ffmpeg.exe",
        ffprobe_path: "C:\\tools\\ffprobe.exe",
        config_path: "C:\\cfg\\filesight.toml",
        default_profile: "default",
        default_recursive: false,
        default_include_videos: true,
        report_filename: "filesight-report.json",
        last_directory: null,
        last_report_path: null,
        last_log_path: null,
        onboarding_seen: true,
      },
    });

    await useAppStore.getState().startScan();
    const scan = client.sent.find((s) => s.command === "scan");
    // Without these the worker cannot find a manually configured FFmpeg
    // and every video fails with FFMPEG_NOT_FOUND.
    expect(scan?.payload.ffmpeg_path).toBe("C:\\tools\\ffmpeg.exe");
    expect(scan?.payload.ffprobe_path).toBe("C:\\tools\\ffprobe.exe");
    expect(scan?.payload.config).toBe("C:\\cfg\\filesight.toml");
  });

  it("sends nulls when nothing is configured", async () => {
    const client = freshStore();
    await useAppStore.getState().startScan();
    const scan = client.sent.find((s) => s.command === "scan");
    expect(scan?.payload.ffmpeg_path).toBeNull();
    expect(scan?.payload.ffprobe_path).toBeNull();
  });

  it("re-checks the environment after settings change", async () => {
    const client = freshStore();
    await useAppStore.getState().bootstrap();
    const before = client.sent.filter((s) => s.command === "get_environment").length;
    await useAppStore.getState().refreshEnvironment();
    const after = client.sent.filter((s) => s.command === "get_environment").length;
    expect(after).toBe(before + 1);
    expect(useAppStore.getState().environment).not.toBeNull();
  });
});

describe("busy-state guards", () => {
  it("treats file operations as busy", () => {
    expect(isBusy("renaming")).toBe(true);
    expect(isBusy("undoing")).toBe(true);
    expect(isBusy("analyzing")).toBe(true);
    expect(isBusy("report_ready")).toBe(false);
    expect(isBusy("idle")).toBe(false);
  });
});
