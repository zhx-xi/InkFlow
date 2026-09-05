/**
 * 日志展示格式化纯函数（#496/#930/#932 共用；无 i18n / React 依赖，900 行护栏拆分）。
 *
 * - interpolateTemplate：{key} 占位插值（缺参保留占位符，与 useI18n 同款规则）
 * - formatTimestamp：ISO → 'YYYY-MM-DD HH:mm:ss'（UTC toISOString 口径；解析失败原样直出）
 * - formatClock：UTC 'HH:mm:ss'（#932 链节点简式时间，勿用本地时区）
 * - formatDuration：#930 三档时长（<1s ms 两位小数 / <60s s 一位小数 / ≥60s m+s）
 * - levelBadgeCls：level → badge 配色
 */

/** {key} 占位符插值：params 缺参保留原占位符；params 同名键覆盖上下文。 */
export function interpolateTemplate(template: string, params?: Record<string, unknown>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : `{${key}}`,
  );
}

/** timestamp 展示：ISO → 'YYYY-MM-DD HH:mm:ss'（UTC 口径）；解析失败原样直出。 */
export function formatTimestamp(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toISOString().slice(0, 19).replace('T', ' ');
}

/** 链节点简式时钟：UTC 'HH:mm:ss'（契约：'2026-09-04T00:01:00Z' → '00:01:00'）。 */
export function formatClock(iso: string): string {
  return formatTimestamp(iso).slice(11, 19);
}

/** 时长格式化：#930 卡片可读性 —— <1s 两位小数 ms、<60s 一位小数 s、≥60s m+s。 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(2)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`;
}

/** level → badge 配色（tokens 语义色）。 */
export function levelBadgeCls(level: string): string {
  if (level === 'ERROR') return 'bg-err/10 text-err';
  if (level === 'WARN') return 'bg-warn/10 text-warn';
  if (level === 'INFO') return 'bg-ok/10 text-ok';
  return 'bg-surface-3 text-ink-2';
}
