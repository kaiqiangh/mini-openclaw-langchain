"use client";

import { useEffect, useLayoutEffect, useMemo, useState } from "react";

type SectionState<T extends string> = Record<T, boolean>;

function cloneState<T extends string>(
  keys: T[],
  source: SectionState<T>,
): SectionState<T> {
  return keys.reduce(
    (acc, key) => {
      acc[key] = source[key];
      return acc;
    },
    {} as SectionState<T>,
  );
}

function fillState<T extends string>(keys: T[], value: boolean): SectionState<T> {
  return keys.reduce(
    (acc, key) => {
      acc[key] = value;
      return acc;
    },
    {} as SectionState<T>,
  );
}

export function usePersistentSectionState<T extends string>({
  storageKey,
  desktopDefaults,
  mobileDefaults,
}: {
  storageKey: string;
  desktopDefaults: SectionState<T>;
  mobileDefaults: SectionState<T>;
}) {
  const keys = useMemo(() => Object.keys(desktopDefaults) as T[], [desktopDefaults]);
  const useSafeLayoutEffect =
    typeof window === "undefined" ? useEffect : useLayoutEffect;

  function getResponsiveDefaults(): SectionState<T> {
    const prefersDesktop =
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function" ||
      window.matchMedia("(min-width: 1024px)").matches;

    return cloneState(keys, prefersDesktop ? desktopDefaults : mobileDefaults);
  }

  function getInitialState(): SectionState<T> {
    const defaults = getResponsiveDefaults();
    if (typeof window === "undefined") {
      return defaults;
    }

    try {
      const raw = window.localStorage.getItem(storageKey);
      if (!raw) {
        return defaults;
      }

      const parsed = JSON.parse(raw) as Partial<Record<T, boolean>>;
      return keys.reduce(
        (acc, key) => {
          acc[key] = parsed[key] ?? defaults[key];
          return acc;
        },
        {} as SectionState<T>,
      );
    } catch {
      return defaults;
    }
  }

  const [sections, setSections] = useState<SectionState<T>>(() =>
    cloneState(keys, desktopDefaults),
  );

  useSafeLayoutEffect(() => {
    setSections(getInitialState());
  }, [desktopDefaults, keys, mobileDefaults, storageKey]);

  function persist(
    next:
      | SectionState<T>
      | ((previous: SectionState<T>) => SectionState<T>),
  ) {
    setSections((previous) => {
      const resolved = typeof next === "function" ? next(previous) : next;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(storageKey, JSON.stringify(resolved));
      }
      return resolved;
    });
  }

  function toggleSection(key: T) {
    persist((previous) => ({
      ...previous,
      [key]: !previous[key],
    }));
  }

  function expandAll() {
    persist(fillState(keys, true));
  }

  function collapseAll() {
    persist(fillState(keys, false));
  }

  return {
    sections,
    setSections: persist,
    toggleSection,
    expandAll,
    collapseAll,
  };
}
