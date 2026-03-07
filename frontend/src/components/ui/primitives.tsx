"use client";

import {
  createContext,
  type KeyboardEvent as ReactKeyboardEvent,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TableHTMLAttributes,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
} from "react";

function cx(...values: Array<string | undefined | false>) {
  return values.filter(Boolean).join(" ");
}

type ClassNameProps = {
  className?: string;
};

type FieldStateProps = {
  invalid?: boolean;
  hintId?: string;
  errorId?: string;
};

function resolveDescribedBy(
  existing: string | undefined,
  hintId: string | undefined,
  errorId: string | undefined,
  invalid: boolean,
): string | undefined {
  const values = [existing, hintId, invalid ? errorId : undefined]
    .filter(Boolean)
    .flatMap((item) => String(item).split(/\s+/).filter(Boolean));
  if (values.length === 0) return undefined;
  return Array.from(new Set(values)).join(" ");
}

export function Panel({
  className,
  ...props
}: HTMLAttributes<HTMLElement> & ClassNameProps) {
  return <section className={cx("ui-panel", className)} {...props} />;
}

export function PanelHeader({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & ClassNameProps) {
  return <div className={cx("ui-panel-header", className)} {...props} />;
}

export function PanelTitle({
  className,
  ...props
}: HTMLAttributes<HTMLHeadingElement> & ClassNameProps) {
  return <h2 className={cx("ui-panel-title", className)} {...props} />;
}

type ButtonVariant = "neutral" | "primary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

export function Button({
  variant = "neutral",
  size = "md",
  loading = false,
  leadingIcon,
  trailingIcon,
  className,
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> &
  ClassNameProps & {
    variant?: ButtonVariant;
    size?: ButtonSize;
    loading?: boolean;
    leadingIcon?: ReactNode;
    trailingIcon?: ReactNode;
  }) {
  const isDisabled = Boolean(disabled || loading);
  return (
    <button
      {...props}
      className={cx(
        "ui-btn",
        size === "sm" && "ui-btn-sm",
        size === "lg" && "ui-btn-lg",
        variant === "primary" && "ui-btn-primary",
        variant === "ghost" && "ui-btn-ghost",
        variant === "danger" && "ui-btn-danger",
        className,
      )}
      disabled={isDisabled}
      aria-busy={loading || undefined}
    >
      {leadingIcon ? <span aria-hidden>{leadingIcon}</span> : null}
      <span>{children}</span>
      {loading ? <span className="ui-btn-spinner" aria-hidden /> : trailingIcon ? <span aria-hidden>{trailingIcon}</span> : null}
    </button>
  );
}

export function Input({
  className,
  invalid = false,
  hintId,
  errorId,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & ClassNameProps & FieldStateProps) {
  const describedBy = resolveDescribedBy(
    props["aria-describedby"],
    hintId,
    errorId,
    invalid,
  );
  return (
    <input
      {...props}
      className={cx("ui-input", invalid && "ui-input-invalid", className)}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
    />
  );
}

export function Select({
  className,
  invalid = false,
  hintId,
  errorId,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & ClassNameProps & FieldStateProps) {
  const describedBy = resolveDescribedBy(
    props["aria-describedby"],
    hintId,
    errorId,
    invalid,
  );
  return (
    <select
      {...props}
      className={cx("ui-select", invalid && "ui-input-invalid", className)}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
    />
  );
}

type BadgeTone = "neutral" | "accent" | "success" | "warn" | "danger";

export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & ClassNameProps & { tone?: BadgeTone }) {
  return (
    <span
      className={cx("ui-badge", `ui-badge-${tone}`, className)}
      {...props}
    />
  );
}

type TabsContextValue = {
  value?: string;
  onChange?: (value: string) => void;
  listId: string;
};

const TabsContext = createContext<TabsContextValue | null>(null);

type TabsListProps = Omit<HTMLAttributes<HTMLDivElement>, "onChange"> &
  ClassNameProps & {
    ariaLabel?: string;
    value?: string;
    onChange?: (value: string) => void;
  };

export function TabsList({
  className,
  ariaLabel,
  value,
  onChange,
  onKeyDown,
  id,
  ...props
}: TabsListProps) {
  const generatedId = useId();
  const listId = id ?? generatedId;
  const contextValue = useMemo(
    () => ({ value, onChange, listId }),
    [listId, onChange, value],
  );

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;

    const keys = ["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"];
    if (!keys.includes(event.key)) return;

    const tabs = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    );
    if (tabs.length === 0) return;

    const activeIndex = tabs.findIndex((tab) => tab.getAttribute("aria-selected") === "true");
    const focusedIndex = tabs.findIndex((tab) => tab === document.activeElement);
    const index = focusedIndex >= 0 ? focusedIndex : Math.max(0, activeIndex);

    let nextIndex = index;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (index + 1) % tabs.length;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (index - 1 + tabs.length) % tabs.length;
    }

    event.preventDefault();
    const next = tabs[nextIndex];
    next.focus();
    next.click();
  };

  return (
    <TabsContext.Provider value={contextValue}>
      <div
        {...props}
        className={cx("ui-tabs", className)}
        role="tablist"
        aria-label={ariaLabel}
        id={listId}
        onKeyDown={handleKeyDown}
      />
    </TabsContext.Provider>
  );
}

type TabButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  ClassNameProps & {
    active?: boolean;
    value?: string;
    controls?: string;
  };

export function TabButton({
  active = false,
  className,
  value,
  id,
  controls,
  onClick,
  ...props
}: TabButtonProps) {
  const tabs = useContext(TabsContext);
  const selected =
    value !== undefined && tabs?.value !== undefined
      ? tabs.value === value
      : active;

  const handleClick: ButtonHTMLAttributes<HTMLButtonElement>["onClick"] = (
    event,
  ) => {
    onClick?.(event);
    if (event.defaultPrevented) return;
    if (value !== undefined) {
      tabs?.onChange?.(value);
    }
  };

  return (
    <button
      {...props}
      className={cx("ui-tab", selected && "active", className)}
      role="tab"
      id={id}
      type="button"
      aria-selected={selected}
      aria-controls={controls}
      tabIndex={selected ? 0 : -1}
      onClick={handleClick}
    />
  );
}

export function TableWrap({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & ClassNameProps) {
  return <div className={cx("ui-table-wrap", className)} {...props} />;
}

export function DataTable({
  className,
  ...props
}: TableHTMLAttributes<HTMLTableElement> & ClassNameProps) {
  return <table className={cx("ui-table", className)} {...props} />;
}

export function Tooltip({
  label,
  className,
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement> &
  ClassNameProps & { label: string; children: ReactNode }) {
  return (
    <span
      className={cx("ui-tooltip", className)}
      data-tip={label}
      tabIndex={0}
      {...props}
    >
      {children}
    </span>
  );
}

export function ModalFrame({
  title,
  children,
  className,
  onClose,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  onClose?: () => void;
}) {
  const titleId = useId();
  const modalRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = modalRef.current;
    if (!node) return;

    const focusableSelector =
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    const focusable = Array.from(
      node.querySelectorAll<HTMLElement>(focusableSelector),
    );

    const initial = focusable[0] ?? node;
    initial.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose?.();
        return;
      }
      if (event.key !== "Tab") return;

      const targets = Array.from(
        node.querySelectorAll<HTMLElement>(focusableSelector),
      );
      if (targets.length === 0) {
        event.preventDefault();
        node.focus();
        return;
      }

      const first = targets[0];
      const last = targets[targets.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      }
      if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    node.addEventListener("keydown", handleKeyDown);
    return () => {
      node.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  return (
    <div
      className="ui-modal-overlay"
      onMouseDown={(event) => {
        if (!onClose) return;
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={modalRef}
        className={cx("ui-modal", className)}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h2 id={titleId} className="ui-panel-title">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

export function Toast({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & ClassNameProps & { children: ReactNode }) {
  return (
    <div className={cx("ui-toast", className)} aria-live="polite" {...props}>
      {children}
    </div>
  );
}

export function Skeleton({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & ClassNameProps) {
  return (
    <div className={cx("ui-skeleton", className)} aria-hidden {...props} />
  );
}

export function EmptyState({
  title,
  description,
  className,
  actionLabel,
  onAction,
}: {
  title: string;
  description: string;
  className?: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className={cx("ui-empty", className)}>
      <strong>{title}</strong>
      <span>{description}</span>
      {actionLabel && onAction ? (
        <Button type="button" size="sm" className="mt-3" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  );
}
