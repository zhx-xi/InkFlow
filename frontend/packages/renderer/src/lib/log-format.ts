/**
 * 日志展示格式化纯函数（#496/#930/#932 共用；无 i18n / React 依赖，900 行护栏拆分）。
 *
 * - interpolateTemplate：{key} 占位插值（缺参保留占位符，与 useI18n 同款规则）
 * - formatTimestamp：ISO → 系统本地时区 'YYYY-MM-DD HH:mm:ss'（ADR-055：存储 UTC /
 *   显示本地，#1000；手拼而非 toLocaleString，避免 locale 与 12/24 小时制漂移；解析失败原样直出）
 * - formatClock：本地 'HH:mm:ss'（#932 链节点简式时间；取自 formatTimestamp）
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

/**
 * timestamp 展示：ISO → 系统本地时区 'YYYY-MM-DD HH:mm:ss'（ADR-055 / #1000）；解析失败原样直出。
 *
 * 前提（审查 #1063 MINOR-5）：消费面 `/api/v1/logs` 的 timestamp 恒带 `Z` 后缀
 * （JSONL 存储 + pydantic model_dump(mode="json")，round-trip 实证）→ `new Date()`
 * 按 UTC 解析后转本地正确。JS 规范下**无偏移** date-time 串按本地解释——若将来
 * 喂入 naive UTC 串（实体端点的 SQLite 常态）会原值显示，接入前需先补 'Z'。
 */
export function formatTimestamp(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  const pad = (value: number) => String(value).padStart(2, '0');
  return (
    `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ` +
    `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`
  );
}

/** 链节点简式时钟：本地 'HH:mm:ss'（#1000：继承 formatTimestamp；契约 '2026-09-04T00:01:00Z' → '08:01:00'）。 */
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
