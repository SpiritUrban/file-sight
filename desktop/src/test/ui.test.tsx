import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import App from "@/App";
import { validateFilename } from "@/lib/filename";
import { MockWorkerClient, MOCK_ENTRIES } from "@/lib/mockWorker";
import { safeParse, workerEventSchema, reportSchema } from "@/lib/schemas";
import { defaultScanOptions, useAppStore } from "@/stores/appStore";

function setup(client = new MockWorkerClient()) {
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
    selectedPath: null,
    filter: "all",
    categoryFilter: "all",
    search: "",
    environment: null,
    profiles: [],
    activeRequestId: null,
    options: { ...defaultScanOptions },
    progress: {
      phase: "", currentFile: null, completed: 0, total: 0,
      percent: 0, succeeded: 0, failed: 0, startedAt: null,
    },
  });
  localStorage.setItem("filesight.onboarding", "1"); // skip onboarding
  return client;
}

async function scanned(client = new MockWorkerClient()) {
  setup(client);
  useAppStore.getState().setDirectory("C:\\Photos");
  await useAppStore.getState().startScan();
  return client;
}

describe("empty state", () => {
  beforeEach(() => setup());

  it("explains local analysis and offers a folder picker", async () => {
    render(<App />);
    expect(
      await screen.findByText(/choose a folder with images or short videos/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/nothing is uploaded/i)).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /choose folder/i }).length,
    ).toBeGreaterThan(0);
  });

  it("disables Start analysis until a folder is chosen", async () => {
    render(<App />);
    const start = await screen.findByRole("button", { name: /start analysis/i });
    expect(start).toBeDisabled();

    useAppStore.getState().setDirectory("C:\\Photos");
    await waitFor(() => expect(start).toBeEnabled());
  });

  it("shows the chosen folder", async () => {
    render(<App />);
    useAppStore.getState().setDirectory("D:\\Media");
    expect(await screen.findByTitle("D:\\Media")).toBeInTheDocument();
  });
});

describe("environment", () => {
  it("shows Python, model and FFmpeg status", async () => {
    setup();
    render(<App />);
    await waitFor(() =>
      expect(screen.getByText(/^Python:$/)).toBeInTheDocument(),
    );
    expect(screen.getByText("3.11.9")).toBeInTheDocument();
    expect(screen.getByText(/FFmpeg:/)).toBeInTheDocument();
  });

  it("surfaces a worker start failure", async () => {
    const client = new MockWorkerClient();
    client.start = async () => {
      throw new Error("Python not found");
    };
    setup(client);
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/python not found/i);
    expect(screen.getByText(/no files were changed/i)).toBeInTheDocument();
  });
});

describe("progress", () => {
  it("reports progress and the current file while scanning", async () => {
    const client = setup(new MockWorkerClient({ stepDelay: 15 }));
    render(<App />);
    useAppStore.getState().setDirectory("C:\\Photos");
    const scan = useAppStore.getState().startScan();

    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole("progressbar")).toBeInTheDocument(),
    );
    await scan;
    expect(client.sent.some((s) => s.command === "scan")).toBe(true);
  });

  it("offers Cancel during a scan and hides it afterwards", async () => {
    setup(new MockWorkerClient({ stepDelay: 15 }));
    render(<App />);
    useAppStore.getState().setDirectory("C:\\Photos");
    const scan = useAppStore.getState().startScan();

    expect(
      await screen.findByRole("button", { name: /^cancel$/i }),
    ).toBeInTheDocument();
    await scan;
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /start analysis/i })).toBeInTheDocument(),
    );
  });
});

describe("results table", () => {
  beforeEach(async () => {
    await scanned();
  });

  it("renders one row per file with its category and status", async () => {
    render(<App />);
    expect(await screen.findByText("IMG_0001.jpg")).toBeInTheDocument();
    expect(screen.getByText("broken.png")).toBeInTheDocument();
    expect(screen.getAllByText("animals").length).toBeGreaterThan(0);
    expect(screen.getByText("failed")).toBeInTheDocument();
    // one header row + four data rows
    expect(screen.getAllByRole("row")).toHaveLength(MOCK_ENTRIES.length + 1);
  });

  it("edits a suggested name and marks the report unsaved", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = await screen.findByLabelText(/suggested name for IMG_0001\.jpg/i);
    await user.clear(input);
    await user.type(input, "my-photo.jpg");

    expect(await screen.findByText(/unsaved changes/i)).toBeInTheDocument();
    expect(useAppStore.getState().report!.files[0].suggested_name).toBe("my-photo.jpg");
  });

  it("shows an inline error and blocks rename for an invalid name", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = await screen.findByLabelText(/suggested name for IMG_0001\.jpg/i);
    await user.clear(input);
    await user.type(input, "bad:name.jpg");

    expect(await screen.findByText(/windows does not allow/i)).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: /rename files/i })).toBeDisabled();
  });

  it("toggles rename for a single file", async () => {
    const user = userEvent.setup();
    render(<App />);
    const checkbox = await screen.findByLabelText(/rename IMG_0001\.jpg/i);
    expect(checkbox).toBeChecked();
    await user.click(checkbox);
    expect(checkbox).not.toBeChecked();
  });

  it("never lets a failed file be selected for rename", async () => {
    render(<App />);
    const checkbox = await screen.findByLabelText(/rename broken\.png/i);
    expect(checkbox).toBeDisabled();
    expect(checkbox).not.toBeChecked();
  });

  it("enables and disables every visible row", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /disable visible/i }));
    expect(screen.getByLabelText(/rename IMG_0001\.jpg/i)).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: /enable visible/i }));
    expect(screen.getByLabelText(/rename IMG_0001\.jpg/i)).toBeChecked();
  });
});

describe("filters and search", () => {
  beforeEach(async () => {
    await scanned();
  });

  it("filters to videos only", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Videos" }));
    expect(screen.getByText("clip.mp4")).toBeInTheDocument();
    expect(screen.queryByText("IMG_0001.jpg")).not.toBeInTheDocument();
  });

  it("searches by caption", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText(/search files/i), "woman");
    await waitFor(() =>
      expect(screen.queryByText("IMG_0001.jpg")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("IMG_0002.jpg")).toBeInTheDocument();
  });

  it("explains an empty result set", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText(/search files/i), "nothing-here");
    expect(await screen.findByText(/no files match/i)).toBeInTheDocument();
  });
});

describe("detail panel", () => {
  beforeEach(async () => {
    await scanned();
  });

  it("prompts for a selection, then shows the file's details", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText(/select a file to see its details/i)).toBeInTheDocument();

    await user.click(screen.getByText("IMG_0001.jpg"));
    const panel = screen.getByLabelText("File details");
    expect(within(panel).getByText("a black dog running through snow")).toBeInTheDocument();
    expect(within(panel).getByText("black dog")).toBeInTheDocument();
    expect(within(panel).getByText(/0\.55 \(rule-based\)/)).toBeInTheDocument();
  });

  it("shows video specifics for a clip", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByText("clip.mp4"));
    const panel = screen.getByLabelText("File details");
    expect(within(panel).getByText("3.2 s")).toBeInTheDocument();
    expect(within(panel).getByText("640 × 360")).toBeInTheDocument();
    expect(within(panel).getByText("h264")).toBeInTheDocument();
    expect(within(panel).getByText(/2 usable of 6 extracted/)).toBeInTheDocument();
  });

  it("hides technical fields behind a toggle", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByText("IMG_0001.jpg"));
    const panel = screen.getByLabelText("File details");
    expect(within(panel).queryByText(/keyword:dog/)).not.toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: /technical details/i }));
    expect(within(panel).getByText(/keyword:dog/)).toBeInTheDocument();
  });

  it("shows the error for a failed file", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByText("broken.png"));
    const panel = screen.getByLabelText("File details");
    expect(within(panel).getByText("UnidentifiedImageError")).toBeInTheDocument();
  });
});

describe("save, validate and dry run", () => {
  beforeEach(async () => {
    await scanned();
  });

  it("saves the report and clears the unsaved marker", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = await screen.findByLabelText(/suggested name for IMG_0001\.jpg/i);
    await user.clear(input);
    await user.type(input, "renamed.jpg");
    await user.click(screen.getByRole("button", { name: /save report/i }));
    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
  });

  it("shows the validation summary in a dialog", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /validate/i }));
    const dialog = await screen.findByRole("dialog", { name: /validation/i });
    expect(within(dialog).getByText("Ready to rename")).toBeInTheDocument();
    expect(within(dialog).getByText("NO_METADATA")).toBeInTheDocument();
  });

  it("shows a dry-run plan and changes nothing", async () => {
    const user = userEvent.setup();
    const client = useAppStore.getState().client as MockWorkerClient;
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /dry run/i }));
    const dialog = await screen.findByRole("dialog", { name: /dry run/i });
    expect(within(dialog).getByText(/3 file\(s\) would be renamed/)).toBeInTheDocument();
    expect(client.sent.some((s) => s.command === "apply_rename")).toBe(false);
  });
});

describe("rename and undo", () => {
  it("requires explicit confirmation before renaming", async () => {
    const user = userEvent.setup();
    const client = await scanned();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /rename files/i }));

    const dialog = await screen.findByRole("dialog", { name: /rename files/i });
    expect(within(dialog).getByText(/3 files will be renamed/)).toBeInTheDocument();
    expect(within(dialog).getByText(/rollback log will be created/i)).toBeInTheDocument();
    // nothing happens until the explicit button is pressed
    expect(client.sent.some((s) => s.command === "apply_rename")).toBe(false);

    await user.click(within(dialog).getByRole("button", { name: /rename 3 files/i }));
    await waitFor(() =>
      expect(client.sent.some((s) => s.command === "apply_rename")).toBe(true),
    );
  });

  it("reports a successful rename with its log path", async () => {
    const user = userEvent.setup();
    await scanned();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /rename files/i }));
    const confirm = await screen.findByRole("dialog", { name: /rename files/i });
    await user.click(within(confirm).getByRole("button", { name: /rename 3 files/i }));

    const result = await screen.findByRole("dialog", { name: /rename completed/i });
    expect(within(result).getByText("Renamed")).toBeInTheDocument();
    expect(within(result).getByText(/filesight-rename-log/)).toBeInTheDocument();
  });

  it("never shows a partial failure as success", async () => {
    const user = userEvent.setup();
    await scanned(new MockWorkerClient({ partialRename: true }));
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /rename files/i }));
    const confirm = await screen.findByRole("dialog", { name: /rename files/i });
    await user.click(within(confirm).getByRole("button", { name: /rename 3 files/i }));

    const result = await screen.findByRole("dialog", {
      name: /did not complete safely/i,
    });
    expect(within(result).getByText(/partially_rolled_back/)).toBeInTheDocument();
    expect(within(result).getByText(/manual attention/i)).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /rename completed/i })).toBeNull();
  });

  it("previews undo before restoring", async () => {
    const user = userEvent.setup();
    await scanned();
    render(<App />);
    // undo is unavailable until a rename produced a log
    expect(screen.getByRole("button", { name: /undo last rename/i })).toBeDisabled();

    await useAppStore.getState().applyRename();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /undo last rename/i })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: /undo last rename/i }));

    const dialog = await screen.findByRole("dialog", { name: /undo last rename/i });
    expect(within(dialog).getByText(/1 files will be restored/)).toBeInTheDocument();
  });
});

describe("accessibility and safety", () => {
  it("closes a dismissible dialog with Escape", async () => {
    const user = userEvent.setup();
    await scanned();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /validate/i }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("labels every interactive control", async () => {
    await scanned();
    render(<App />);
    await screen.findByText("IMG_0001.jpg");
    for (const box of screen.getAllByRole("checkbox")) {
      expect(box).toHaveAccessibleName();
    }
    for (const button of screen.getAllByRole("button")) {
      expect(button).toHaveAccessibleName();
    }
  });
});

describe("runtime validation", () => {
  it("accepts a well-formed worker event", () => {
    const parsed = safeParse(workerEventSchema, {
      request_id: "a", event: "progress", data: { percent: 10 },
    });
    expect(parsed.ok).toBe(true);
  });

  it("rejects a malformed event instead of throwing", () => {
    const parsed = safeParse(workerEventSchema, { nope: true });
    expect(parsed.ok).toBe(false);
  });

  it("rejects a report with the wrong shape", () => {
    const parsed = safeParse(reportSchema, { schema_version: "1.3" });
    expect(parsed.ok).toBe(false);
  });
});

describe("filename rules", () => {
  it("mirrors the Python validation rules", () => {
    expect(validateFilename("photo.jpg", "IMG.jpg")).toBeNull();
    expect(validateFilename("", "IMG.jpg")).toMatch(/empty/i);
    expect(validateFilename("a<b.jpg", "IMG.jpg")).toMatch(/does not allow/i);
    expect(validateFilename("..\\up.jpg", "IMG.jpg")).toMatch(/not a path/i);
    expect(validateFilename("NUL.jpg", "IMG.jpg")).toMatch(/reserve/i);
    expect(validateFilename("photo.png", "IMG.jpg")).toMatch(/extension/i);
    expect(validateFilename("photo.jpg ", "IMG.jpg")).toMatch(/space or a dot/i);
    expect(validateFilename(`${"x".repeat(300)}.jpg`, "IMG.jpg")).toMatch(/too long/i);
  });
});
