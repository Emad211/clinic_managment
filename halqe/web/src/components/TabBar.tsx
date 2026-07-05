"use client";

/**
 * TabBar + TabPanel — accessible tab navigation for the patient cockpit.
 *
 * ARIA (WAI-ARIA tabs pattern):
 *   - the tab strip is role="tablist"
 *   - each tab is role="tab" with aria-selected + aria-controls (→ its panel id)
 *     and a matching id (→ referenced by the panel's aria-labelledby)
 *   - each panel is role="tabpanel" with aria-labelledby (→ its tab id)
 *   - keyboard: ArrowLeft/ArrowRight move between tabs (RTL-aware — ArrowLeft goes
 *     to the NEXT tab in a right-to-left strip), Home/End jump to first/last.
 *     Roving tabindex: only the active tab is in the tab order (tabIndex 0), the
 *     rest are tabIndex -1 and reachable via arrows (per the ARIA pattern).
 *
 * DOM retention (per the UX spec "tabs keep DOM, don't unmount"): every panel
 * stays mounted; inactive panels are hidden with the `hidden` attribute so their
 * state (e.g. an open form, a fetched list) survives tab switches and they are
 * removed from the a11y tree while hidden.
 *
 * Counters: a tab may carry a `count` — shown as a small badge on the label and
 * folded into the aria-label ("… ۳ مورد در انتظار") so it is announced.
 */

import { useRef, type ReactNode, type KeyboardEvent } from "react";
import styles from "@/app/patients/[uuid]/record.module.css";

export interface TabDef<K extends string = string> {
  key: K;
  label: string;
  /** Optional pending-work counter shown as a badge + announced. */
  count?: number;
}

export interface TabBarProps<K extends string = string> {
  tabs: TabDef<K>[];
  active: K;
  onChange: (key: K) => void;
  /** Accessible name for the tablist. */
  ariaLabel: string;
  /** Stable id prefix so tab/panel ids are unique + linkable. */
  idPrefix: string;
}

/** Deterministic ids so a TabPanel can reference the same tab id. */
export function tabId(idPrefix: string, key: string): string {
  return `${idPrefix}-tab-${key}`;
}
export function panelId(idPrefix: string, key: string): string {
  return `${idPrefix}-panel-${key}`;
}

export function TabBar<K extends string = string>({
  tabs,
  active,
  onChange,
  ariaLabel,
  idPrefix,
}: TabBarProps<K>) {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function focusTab(key: K) {
    tabRefs.current[key]?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const idx = tabs.findIndex((t) => t.key === active);
    if (idx < 0) return;
    let next = idx;
    switch (e.key) {
      // RTL strip: ArrowLeft advances (visually leftward = next), ArrowRight goes back.
      case "ArrowLeft":
        next = (idx + 1) % tabs.length;
        break;
      case "ArrowRight":
        next = (idx - 1 + tabs.length) % tabs.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = tabs.length - 1;
        break;
      default:
        return;
    }
    e.preventDefault();
    const nextKey = tabs[next].key;
    onChange(nextKey);
    focusTab(nextKey);
  }

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={styles.tabList}
      onKeyDown={onKeyDown}
    >
      {tabs.map((t) => {
        const selected = t.key === active;
        const hasCount = typeof t.count === "number" && t.count > 0;
        const ariaLabelText = hasCount
          ? `${t.label} — ${t.count} مورد در انتظار`
          : t.label;
        return (
          <button
            key={t.key}
            ref={(el) => {
              tabRefs.current[t.key] = el;
            }}
            role="tab"
            id={tabId(idPrefix, t.key)}
            aria-selected={selected}
            aria-controls={panelId(idPrefix, t.key)}
            aria-label={hasCount ? ariaLabelText : undefined}
            tabIndex={selected ? 0 : -1}
            className={`${styles.tab} ${selected ? styles.tabActive : ""}`}
            onClick={() => onChange(t.key)}
            type="button"
            data-testid={`tab-${t.key}`}
          >
            <span>{t.label}</span>
            {hasCount && (
              <span className={styles.tabCount} aria-hidden="true">
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// TabPanel — one panel; hidden (but mounted) when inactive
// ────────────────────────────────────────────────────────────

export function TabPanel({
  idPrefix,
  tabKey,
  active,
  children,
}: {
  idPrefix: string;
  tabKey: string;
  active: string;
  children: ReactNode;
}) {
  const isActive = tabKey === active;
  return (
    <div
      role="tabpanel"
      id={panelId(idPrefix, tabKey)}
      aria-labelledby={tabId(idPrefix, tabKey)}
      hidden={!isActive}
      tabIndex={0}
      data-testid={`tabpanel-${tabKey}`}
    >
      {children}
    </div>
  );
}
