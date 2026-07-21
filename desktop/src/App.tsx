import { AlertTriangle, FolderOpen, Save, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Dialog } from "@/components/Dialog";
import {
  ConfirmRenameDialog,
  DryRunDialog,
  RenameResultDialog,
  UndoDialog,
  ValidationDialog,
} from "@/features/Dialogs";
import { DetailPanel } from "@/features/DetailPanel";
import { EnvironmentBar } from "@/features/EnvironmentBar";
import { FilterBar } from "@/features/FilterBar";
import { MediaTable } from "@/features/MediaTable";
import { ProgressBar } from "@/features/ProgressBar";
import { SettingsDialog } from "@/features/SettingsDialog";
import { Toolbar } from "@/features/Toolbar";
import { chooseDirectory, openPath, revealPath } from "@/lib/platform";
import { isBusy, isFileOperation, useAppStore } from "@/stores/appStore";
import type { UndoResult } from "@/types";

export default function App() {
  const uiState = useAppStore((s) => s.uiState);
  const report = useAppStore((s) => s.report);
  const dirty = useAppStore((s) => s.dirty);
  const options = useAppStore((s) => s.options);
  const errorMessage = useAppStore((s) => s.errorMessage);
  const errorDetail = useAppStore((s) => s.errorDetail);
  const clearError = useAppStore((s) => s.clearError);
  const validation = useAppStore((s) => s.validation);
  const plan = useAppStore((s) => s.plan);
  const renameResult = useAppStore((s) => s.renameResult);
  const logPath = useAppStore((s) => s.logPath);

  const bootstrap = useAppStore((s) => s.bootstrap);
  const setDirectory = useAppStore((s) => s.setDirectory);
  const saveReport = useAppStore((s) => s.saveReport);
  const validateReport = useAppStore((s) => s.validateReport);
  const buildPlan = useAppStore((s) => s.buildPlan);
  const applyRename = useAppStore((s) => s.applyRename);
  const undoLast = useAppStore((s) => s.undoLast);
  const select = useAppStore((s) => s.select);
  const entryErrors = useAppStore((s) => s.entryErrors);

  const [showValidation, setShowValidation] = useState(false);
  const [showPlan, setShowPlan] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [undoPreview, setUndoPreview] = useState<UndoResult | null>(null);
  const [showUndo, setShowUndo] = useState(false);

  useEffect(() => {
    void bootstrap();
    if (!localStorage.getItem("filesight.onboarding")) setShowOnboarding(true);
  }, [bootstrap]);

  // A file operation must not be interrupted by closing the window.
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (isFileOperation(uiState) || dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [uiState, dirty]);

  const onChooseFolder = useCallback(async () => {
    const directory = await chooseDirectory();
    if (directory) setDirectory(directory);
  }, [setDirectory]);

  const enabledCount =
    report?.files.filter((f) => f.status === "success" && f.rename_enabled).length ?? 0;
  const hasNameErrors = entryErrors().size > 0;
  const busy = isBusy(uiState);
  const canRename = Boolean(report) && enabledCount > 0 && !hasNameErrors && !busy;

  const runValidate = async () => {
    const result = await validateReport();
    if (result) setShowValidation(true);
  };

  const runDryRun = async () => {
    if (dirty) await saveReport();
    const built = await buildPlan();
    if (built) setShowPlan(true);
  };

  const runRename = async () => {
    setShowConfirm(false);
    if (dirty) await saveReport();
    const result = await applyRename();
    if (result) setShowResult(true);
  };

  const openUndo = async () => {
    const preview = await undoLast(undefined, true);
    setUndoPreview(preview);
    setShowUndo(true);
  };

  const confirmUndo = async () => {
    setShowUndo(false);
    await undoLast(undefined, false);
  };

  return (
    <div className="flex h-screen flex-col gap-2 p-3">
      <header className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">FileSight</h1>
        <EnvironmentBar />
      </header>

      <Toolbar onChooseFolder={onChooseFolder} onOpenSettings={() => setShowSettings(true)} />
      <ProgressBar />

      {errorMessage ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 p-3 text-sm"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden />
          <div className="flex-1">
            <p className="font-medium text-red-900">{errorMessage}</p>
            <p className="text-red-800">No files were changed.</p>
            {errorDetail ? (
              <p className="mt-1 font-mono text-xs text-red-700">{errorDetail}</p>
            ) : null}
          </div>
          <button type="button" className="btn-secondary" onClick={clearError}>
            Dismiss
          </button>
        </div>
      ) : null}

      {!report ? (
        <div className="panel flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
          <FolderOpen className="h-10 w-10 text-slate-400" aria-hidden />
          <h2 className="text-base font-medium">
            Choose a folder with images or short videos.
          </h2>
          <p className="max-w-md text-sm text-slate-600">
            FileSight analyzes files locally. Nothing is uploaded. The first
            analysis may download an AI model. No file is renamed until you
            confirm the plan.
          </p>
          <button type="button" className="btn-primary" onClick={onChooseFolder}>
            Choose folder
          </button>
        </div>
      ) : (
        <>
          <FilterBar />
          <div className="flex min-h-0 flex-1 gap-2">
            <MediaTable />
            <DetailPanel />
          </div>

          <footer className="panel flex flex-wrap items-center gap-2 p-2">
            {dirty ? (
              <span className="flex items-center gap-1 text-sm text-amber-700">
                <AlertTriangle className="h-4 w-4" aria-hidden />
                Unsaved changes
              </span>
            ) : (
              <span className="text-sm text-slate-500">Saved</span>
            )}
            <span className="text-sm text-slate-500">
              {enabledCount} of {report.files.length} selected for rename
            </span>
            <div className="flex-1" />

            <button
              type="button"
              className="btn-secondary"
              onClick={() => void saveReport()}
              disabled={!dirty || busy}
            >
              <Save className="h-4 w-4" aria-hidden />
              Save report
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void runValidate()}
              disabled={busy}
            >
              <ShieldCheck className="h-4 w-4" aria-hidden />
              Validate
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void runDryRun()}
              disabled={busy}
            >
              Dry run
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => setShowConfirm(true)}
              disabled={!canRename}
              title={
                hasNameErrors
                  ? "Fix the highlighted names first"
                  : enabledCount === 0
                    ? "Enable at least one file"
                    : undefined
              }
            >
              Rename files
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void openUndo()}
              disabled={!logPath || busy}
            >
              Undo last rename
            </button>
          </footer>
        </>
      )}

      <ValidationDialog
        result={showValidation ? validation : null}
        onClose={() => setShowValidation(false)}
        onSelectIssue={(entryIndex) => {
          if (entryIndex !== null && report?.files[entryIndex]) {
            select(report.files[entryIndex].original_path);
            setShowValidation(false);
          }
        }}
      />

      <DryRunDialog
        plan={showPlan ? plan : null}
        onClose={() => setShowPlan(false)}
        onConfirm={() => {
          setShowPlan(false);
          setShowConfirm(true);
        }}
      />

      <ConfirmRenameDialog
        open={showConfirm}
        count={enabledCount}
        onCancel={() => setShowConfirm(false)}
        onConfirm={() => void runRename()}
      />

      {showResult ? (
        <RenameResultDialog
          result={renameResult}
          onClose={() => setShowResult(false)}
          onUndo={() => {
            setShowResult(false);
            void openUndo();
          }}
          onOpenFolder={() => void openPath(options.directory)}
          onOpenLog={() => void revealPath(renameResult?.log_path ?? "")}
        />
      ) : null}

      <UndoDialog
        open={showUndo}
        preview={undoPreview}
        onCancel={() => setShowUndo(false)}
        onConfirm={() => void confirmUndo()}
      />

      <SettingsDialog open={showSettings} onClose={() => setShowSettings(false)} />

      <Dialog
        open={showOnboarding}
        title="Welcome to FileSight"
        onClose={() => setShowOnboarding(false)}
        footer={
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              localStorage.setItem("filesight.onboarding", "1");
              setShowOnboarding(false);
            }}
          >
            Continue
          </button>
        }
      >
        <p className="mb-2">FileSight analyzes files locally.</p>
        <ul className="list-inside list-disc space-y-1 text-slate-700">
          <li>The first analysis may download an AI model.</li>
          <li>The model and Python dependencies can use several gigabytes of disk space.</li>
          <li>No file is renamed until you confirm the rename plan.</li>
        </ul>
      </Dialog>
    </div>
  );
}
