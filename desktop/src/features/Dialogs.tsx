import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

import { Dialog } from "@/components/Dialog";
import { useTranslation } from "@/lib/i18n";
import type {
  RenamePlan,
  RenameResult,
  UndoResult,
  ValidationResult,
} from "@/types";

export function ValidationDialog({
  result,
  onClose,
  onSelectIssue,
}: {
  result: ValidationResult | null;
  onClose: () => void;
  onSelectIssue: (entryIndex: number | null) => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog
      open={result !== null}
      title={t("Validation")}
      onClose={onClose}
      footer={
        <button type="button" className="btn-primary" onClick={onClose}>
          {t("Close")}
        </button>
      }
    >
      {result ? (
        <>
          <dl className="mb-3 grid grid-cols-2 gap-x-6 gap-y-1">
            <div className="flex justify-between">
              <dt>Ready to rename</dt>
              <dd className="font-medium">{result.ready}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Skipped</dt>
              <dd className="font-medium">{result.skipped}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Warnings</dt>
              <dd className="font-medium">{result.warnings.length}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Errors</dt>
              <dd className="font-medium">{result.errors.length}</dd>
            </div>
          </dl>

          {result.errors.length === 0 && result.warnings.length === 0 ? (
            <p className="flex items-center gap-2 text-emerald-700">
              <CheckCircle2 className="h-4 w-4" aria-hidden />
              {t("The report is valid.")}
            </p>
          ) : null}

          {[...result.errors, ...result.warnings].map((issue, index) => (
            <button
              key={`${issue.code}-${index}`}
              type="button"
              onClick={() => onSelectIssue(issue.entry_index)}
              className="mt-2 flex w-full gap-2 rounded border border-slate-200 p-2 text-left hover:bg-slate-50"
            >
              {issue.severity === "error" ? (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden />
              ) : (
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" aria-hidden />
              )}
              <span>
                <span className="font-mono text-xs text-slate-500">{issue.code}</span>
                <br />
                {issue.message}
                {issue.path ? (
                  <>
                    <br />
                    <span className="text-xs text-slate-500">{issue.path}</span>
                  </>
                ) : null}
              </span>
            </button>
          ))}
        </>
      ) : null}
    </Dialog>
  );
}

export function DryRunDialog({
  plan,
  onClose,
  onConfirm,
}: {
  plan: RenamePlan | null;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  const renames = plan?.items.filter((item) => item.action === "rename") ?? [];
  const skips = plan?.items.filter((item) => item.action === "skip") ?? [];
  return (
    <Dialog
      open={plan !== null}
      title={t("Dry run — nothing has been changed")}
      onClose={onClose}
      width="max-w-3xl"
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            {t("Close")}
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={onConfirm}
            disabled={!plan?.valid || renames.length === 0}
          >
            {t("Continue to rename")}
          </button>
        </>
      }
    >
      {plan ? (
        <>
          <p className="mb-2">
            {renames.length} file(s) would be renamed, {skips.length} skipped.
            {plan.errors.length > 0 ? (
              <span className="ml-1 font-medium text-red-700">
                {plan.errors.length} error(s) block the operation.
              </span>
            ) : null}
          </p>
          <p className="mb-3 text-xs text-slate-500">
            Rollback log would be written to {plan.log_path}
          </p>
          <ul className="space-y-1">
            {renames.map((item) => (
              <li key={item.original_path} className="rounded border border-slate-200 p-2">
                <div className="text-xs text-slate-500">FROM</div>
                <div className="break-all">{item.original_name}</div>
                <div className="mt-1 text-xs text-slate-500">TO</div>
                <div className="break-all font-medium">{item.target_name}</div>
              </li>
            ))}
            {skips.map((item) => (
              <li
                key={item.original_path}
                className="rounded border border-dashed border-slate-200 p-2 text-slate-500"
              >
                SKIPPED — {item.original_name}
                <div className="text-xs">{item.skip_reason}</div>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Dialog>
  );
}

export function ConfirmRenameDialog({
  open,
  count,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  count: number;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog
      open={open}
      title={t("Rename files")}
      onClose={onCancel}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onCancel}>
            {t("Cancel")}
          </button>
          {/* Explicit label, never a bare "OK" for a destructive action. */}
          <button type="button" className="btn-primary" onClick={onConfirm}>
            Rename {count} files
          </button>
        </>
      }
    >
      <p className="mb-2">{count} files will be renamed.</p>
      <ul className="list-inside list-disc text-slate-600">
        <li>A rollback log will be created.</li>
        <li>Existing files will not be overwritten.</li>
        <li>You can undo this afterwards.</li>
      </ul>
    </Dialog>
  );
}

export function RenameResultDialog({
  result,
  onClose,
  onUndo,
  onOpenFolder,
  onOpenLog,
}: {
  result: RenameResult | null;
  onClose: () => void;
  onUndo: () => void;
  onOpenFolder: () => void;
  onOpenLog: () => void;
}) {
  const { t } = useTranslation();
  if (!result) return null;
  const clean = result.status === "completed";
  const partial =
    result.status === "partially_rolled_back" || result.status === "partially_undone";

  return (
    <Dialog
      open
      title={clean ? t("Rename completed") : t("Rename did not complete safely")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onOpenFolder}>
            {t("Open folder")}
          </button>
          <button type="button" className="btn-secondary" onClick={onOpenLog}>
            {t("Open log location")}
          </button>
          {clean ? (
            <button type="button" className="btn-secondary" onClick={onUndo}>
              {t("Undo")}
            </button>
          ) : null}
          <button type="button" className="btn-primary" onClick={onClose}>
            {t("Close")}
          </button>
        </>
      }
    >
      <dl className="mb-3 space-y-1">
        <div className="flex justify-between">
          <dt>Renamed</dt>
          <dd className="font-medium">{result.renamed}</dd>
        </div>
        <div className="flex justify-between">
          <dt>Skipped</dt>
          <dd className="font-medium">{result.skipped}</dd>
        </div>
        <div className="flex justify-between">
          <dt>Failed</dt>
          <dd className="font-medium">{result.failed}</dd>
        </div>
        {partial ? (
          <div className="flex justify-between">
            <dt>Rolled back</dt>
            <dd className="font-medium">{result.rolled_back}</dd>
          </div>
        ) : null}
      </dl>

      {!clean ? (
        <div className="mb-3 rounded border border-amber-300 bg-amber-50 p-2">
          <p className="font-medium text-amber-900">
            Status: {result.status}
          </p>
          {result.error ? (
            <p className="mt-1 text-amber-800">{result.error}</p>
          ) : null}
          {!result.all_restored ? (
            <p className="mt-1 text-amber-800">
              Some files need manual attention — see the log for their current
              location. No file content was changed.
            </p>
          ) : null}
        </div>
      ) : null}

      <p className="break-all text-xs text-slate-500">Log: {result.log_path}</p>
    </Dialog>
  );
}

export function UndoDialog({
  open,
  preview,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  preview: UndoResult | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  const operations = (preview?.operations ?? []) as Array<{
    from?: string;
    to?: string;
  }>;
  const blocked = preview?.status === "blocked";
  const already = preview?.status === "already_undone";

  return (
    <Dialog
      open={open}
      title={t("Undo last rename")}
      onClose={onCancel}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onCancel}>
            {t("Cancel")}
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={onConfirm}
            disabled={blocked || already || operations.length === 0}
          >
            Restore {operations.length} files
          </button>
        </>
      }
    >
      {already ? (
        <p>This log has already been undone. Nothing to do.</p>
      ) : blocked ? (
        <>
          <p className="mb-2 text-red-700">Undo is not possible:</p>
          <ul className="space-y-1">
            {(preview?.errors ?? []).map((issue, index) => (
              <li key={index} className="rounded border border-red-200 bg-red-50 p-2">
                <span className="font-mono text-xs">{issue.code}</span>
                <br />
                {issue.message}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <p className="mb-2">
            {operations.length} files will be restored to their original names.
          </p>
          <ul className="space-y-1 text-xs">
            {operations.slice(0, 50).map((operation, index) => (
              <li key={index} className="break-all rounded border border-slate-200 p-1.5">
                {operation.from} → {operation.to}
              </li>
            ))}
          </ul>
        </>
      )}
    </Dialog>
  );
}
