"use client";

import {
  type HTMLAttributes,
  type ReactNode,
  useEffect,
  useState,
} from "react";

function cx(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function PageLayout({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <main
      id="main-content"
      className={cx("ui-page", className)}
      {...props}
    >
      {children}
    </main>
  );
}

export function PageStack({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <section className={cx("ui-page-stack", className)} {...props}>
      {children}
    </section>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  meta,
  actions,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cx("ui-page-header panel-shell", className)}>
      <div className="ui-page-header-main">
        {eyebrow ? <div className="ui-page-eyebrow">{eyebrow}</div> : null}
        <div className="ui-page-title-row">
          <div className="min-w-0">
            <h1 className="ui-page-title">{title}</h1>
            {description ? (
              <p className="ui-page-description">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="ui-page-actions">{actions}</div> : null}
        </div>
        {meta ? <div className="ui-page-meta">{meta}</div> : null}
      </div>
    </header>
  );
}

export function FilterBar({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("ui-filter-bar", className)} {...props}>
      {children}
    </div>
  );
}

export function FilterGrid({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("ui-filter-grid", className)} {...props}>
      {children}
    </div>
  );
}

export function MetricGrid({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("ui-metric-grid", className)} {...props}>
      {children}
    </div>
  );
}

export function MetricCard({
  label,
  value,
  meta,
  tone = "neutral",
  className,
}: {
  label: string;
  value: ReactNode;
  meta?: ReactNode;
  tone?: "neutral" | "accent" | "signal" | "success" | "warn" | "danger";
  className?: string;
}) {
  return (
    <article className={cx("ui-metric-card", `ui-metric-card-${tone}`, className)}>
      <div className="ui-metric-label">{label}</div>
      <div className="ui-metric-value">{value}</div>
      {meta ? <div className="ui-metric-meta">{meta}</div> : null}
    </article>
  );
}

export function SectionCard({
  title,
  description,
  toolbar,
  children,
  className,
  contentClassName,
}: {
  title: string;
  description?: ReactNode;
  toolbar?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  return (
    <section className={cx("ui-section-card panel-shell", className)}>
      <div className="ui-section-header">
        <div className="min-w-0">
          <h2 className="ui-section-title">{title}</h2>
          {description ? (
            <div className="ui-section-description">{description}</div>
          ) : null}
        </div>
        {toolbar ? <div className="ui-section-toolbar">{toolbar}</div> : null}
      </div>
      <div className={cx("ui-section-content", contentClassName)}>{children}</div>
    </section>
  );
}

export function SectionStack({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("ui-section-stack", className)} {...props}>
      {children}
    </div>
  );
}

export function DismissibleHint({
  storageKey,
  title,
  description,
  className,
  children,
}: {
  storageKey: string;
  title: string;
  description: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    try {
      setDismissed(window.localStorage.getItem(storageKey) === "1");
    } catch {
      setDismissed(false);
    }
  }, [storageKey]);

  if (dismissed) {
    return null;
  }

  return (
    <aside className={cx("ui-hint", className)} aria-label={title}>
      <div className="ui-hint-copy">
        <div className="ui-hint-title">{title}</div>
        <div className="ui-hint-description">{description}</div>
      </div>
      {children ? <div className="ui-hint-actions">{children}</div> : null}
      <button
        type="button"
        className="ui-hint-dismiss"
        onClick={() => {
          setDismissed(true);
          try {
            window.localStorage.setItem(storageKey, "1");
          } catch {
            // ignore storage failures
          }
        }}
      >
        Dismiss
      </button>
    </aside>
  );
}
