import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TableHTMLAttributes,
} from "react";

function cx(...values: Array<string | undefined | false>) {
  return values.filter(Boolean).join(" ");
}

type ClassNameProps = {
  className?: string;
};

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

export function Button({
  variant = "neutral",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> &
  ClassNameProps & { variant?: ButtonVariant }) {
  return (
    <button
      className={cx(
        "ui-btn",
        variant === "primary" && "ui-btn-primary",
        variant === "ghost" && "ui-btn-ghost",
        variant === "danger" && "ui-btn-danger",
        className,
      )}
      {...props}
    />
  );
}

export function Input({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & ClassNameProps) {
  return <input className={cx("ui-input", className)} {...props} />;
}

export function Select({
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & ClassNameProps) {
  return <select className={cx("ui-select", className)} {...props} />;
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

export function TabsList({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & ClassNameProps) {
  return <div className={cx("ui-tabs", className)} {...props} />;
}

export function TabButton({
  active = false,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> &
  ClassNameProps & { active?: boolean }) {
  return (
    <button
      className={cx("ui-tab", active && "active", className)}
      {...props}
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
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="ui-modal-overlay">
      <div
        className={cx("ui-modal", className)}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
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
}: {
  title: string;
  description: string;
  className?: string;
}) {
  return (
    <div className={cx("ui-empty", className)}>
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}
