"use client";

/**
 * PerDiseaseIndicators — per-disease indicator blocks (فاز ۱ cockpit overview).
 *
 * One block per active chronic condition (from record.per_disease). Each block:
 *   - a header with the disease name + its own control badge + risk-tier badge.
 *   - a grid of indicator tiles. Each tile shows: big value + unit, target,
 *     a direction-aware delta (▲/▼/– + improving colour), and an ok/warn/danger
 *     level badge (colour + shape/icon, never colour alone).
 *
 * graceful fallback (قید مقدس): renders only when `perDisease` has entries. When
 * the backend omits per_disease (older backend) the parent passes undefined/[]
 * and this component returns null — no empty section. A block with zero indicators
 * still shows its header (control/risk are meaningful on their own) plus a note.
 *
 * suggestion-only: this is a data read-out; the physician decides. No action.
 */

import {
  type PerDiseaseDTO,
  type PerDiseaseIndicatorDTO,
  type IndicatorDeltaDTO,
} from "@/lib/api";
import { toFarsiDigits } from "@/lib/jalali";
import {
  CONTROL_META,
  RISK_META,
  indicatorLevelMeta,
} from "@/lib/clinical-status";
import styles from "@/app/patients/[uuid]/record.module.css";

// ────────────────────────────────────────────────────────────
// Delta chip — arrow + colour, both signals (never colour alone)
// ────────────────────────────────────────────────────────────

const DELTA_ARROW: Record<IndicatorDeltaDTO["dir"], string> = {
  up: "▲",
  down: "▼",
  flat: "–",
};

function DeltaChip({ delta }: { delta: IndicatorDeltaDTO }) {
  const arrow = DELTA_ARROW[delta.dir] ?? "–";
  // improving → green, worsening → red, flat → neutral.
  const cls =
    delta.dir === "flat"
      ? styles.deltaFlat
      : delta.improving
        ? styles.deltaImproving
        : styles.deltaWorsening;
  const magnitude = Math.abs(delta.value);
  const trend =
    delta.dir === "flat"
      ? "بدون تغییر"
      : delta.improving
        ? "روند بهبود"
        : "روند بدتر شدن";

  return (
    <span
      className={`${styles.deltaChip} ${cls}`}
      data-dir={delta.dir}
      data-improving={delta.improving}
      aria-label={`تغییر نسبت به اندازه‌گیری قبلی: ${trend}`}
    >
      <span aria-hidden="true">{arrow}</span>
      <span className={styles.deltaValue}>{toFarsiDigits(magnitude)}</span>
    </span>
  );
}

// ────────────────────────────────────────────────────────────
// One indicator tile
// ────────────────────────────────────────────────────────────

function IndicatorTile({ ind }: { ind: PerDiseaseIndicatorDTO }) {
  const lvl = indicatorLevelMeta(ind.level);
  const hasLevel = ind.level === "ok" || ind.level === "warn" || ind.level === "danger";
  const targetText =
    ind.target === null || ind.target === undefined
      ? null
      : toFarsiDigits(String(ind.target));

  return (
    <div
      className={styles.indicatorTile}
      data-testid={`indicator-tile-${ind.key}`}
      data-level={ind.level ?? "none"}
    >
      <div className={styles.indicatorTileHead}>
        <span className={styles.indicatorLabel}>{ind.label}</span>
        {hasLevel && (
          <span
            className={`${styles.levelBadge} ${styles[lvl.className]}`}
            aria-label={`وضعیت: ${lvl.label}`}
            data-testid={`indicator-level-${ind.key}`}
          >
            <span aria-hidden="true">{lvl.icon}</span> {lvl.label}
          </span>
        )}
      </div>

      <div className={styles.indicatorValueRow}>
        <span className={styles.indicatorValue}>
          {ind.value === null || ind.value === undefined
            ? "—"
            : toFarsiDigits(String(ind.value))}
        </span>
        {ind.unit && <span className={styles.indicatorUnit}>{ind.unit}</span>}
        {ind.delta && <DeltaChip delta={ind.delta} />}
      </div>

      {targetText && (
        <div className={styles.indicatorTarget}>
          هدف: {targetText}
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// One disease block
// ────────────────────────────────────────────────────────────

function DiseaseBlock({ disease }: { disease: PerDiseaseDTO }) {
  const ctrl = CONTROL_META[disease.control.status];
  const rsk = RISK_META[disease.risk_level];

  return (
    <div
      className={styles.diseaseBlock}
      data-testid={`disease-block-${disease.condition_code}`}
    >
      <div className={styles.diseaseBlockHeader}>
        <h3 className={styles.diseaseName}>{disease.condition_name}</h3>
        <div className={styles.diseaseBadges}>
          <span
            className={`${styles.statusBadge} ${styles[ctrl.className]}`}
            data-status={disease.control.status}
            aria-label={`کنترل ${disease.condition_name}: ${disease.control.label}`}
          >
            <span className={styles.statusBadgeIcon} aria-hidden="true">{ctrl.icon}</span>
            {disease.control.label}
          </span>
          <span
            className={`${styles.statusBadge} ${styles[rsk.className]}`}
            data-risk={disease.risk_level}
            aria-label={`خطر ${disease.condition_name}: ${rsk.label}`}
          >
            <span className={styles.statusBadgeIcon} aria-hidden="true">{rsk.icon}</span>
            خطر: {rsk.label}
          </span>
        </div>
      </div>

      {disease.indicators.length === 0 ? (
        <p className={styles.emptyNote}>شاخصِ داده‌داری برای این بیماری ثبت نشده است.</p>
      ) : (
        <div className={styles.indicatorGrid}>
          {disease.indicators.map((ind) => (
            <IndicatorTile key={ind.key} ind={ind} />
          ))}
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// Main export
// ────────────────────────────────────────────────────────────

export function PerDiseaseIndicators({
  perDisease,
}: {
  perDisease?: PerDiseaseDTO[];
}) {
  // graceful fallback: nothing configured / older backend → render nothing.
  if (!perDisease || perDisease.length === 0) return null;

  return (
    <section
      className={`${styles.card} ${styles.section}`}
      aria-label="شاخص‌های هر بیماری"
      data-testid="per-disease-indicators"
    >
      <h2 className={styles.sectionTitle}>شاخص‌های هر بیماری</h2>
      <div className={styles.diseaseBlockList}>
        {perDisease.map((d) => (
          <DiseaseBlock key={d.condition_code} disease={d} />
        ))}
      </div>
    </section>
  );
}
