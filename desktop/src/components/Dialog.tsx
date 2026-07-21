import { useEffect, useRef } from "react";

interface DialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  /** Escape and the backdrop are disabled while a file operation runs. */
  dismissible?: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}

/**
 * Modal dialog with focus trapping. Escape closes only when dismissible,
 * so a rename in progress cannot be dismissed by accident.
 */
export function Dialog({
  open,
  title,
  onClose,
  dismissible = true,
  children,
  footer,
  width = "max-w-2xl",
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && dismissible) {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previous?.focus?.();
    };
  }, [open, dismissible, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(event) => {
        if (dismissible && event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={`panel w-full ${width} max-h-[85vh] overflow-hidden shadow-xl outline-none`}
      >
        <header className="border-b border-slate-200 px-5 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
        </header>
        <div className="max-h-[60vh] overflow-auto px-5 py-4 text-sm">
          {children}
        </div>
        {footer ? (
          <footer className="flex justify-end gap-2 border-t border-slate-200 bg-slate-50 px-5 py-3">
            {footer}
          </footer>
        ) : null}
      </div>
    </div>
  );
}
