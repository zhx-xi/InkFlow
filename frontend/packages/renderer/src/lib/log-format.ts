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
 * 存储/传输层（DB/API/MCP/`--json`）一律 UTC，显示层统一换算系统本地时区。
 * naive date-time 串 = UTC 存储口径（ADR-055 后续范围收口 #1069）：实体端点经
 * SQLite `DateTime` 剥 tzinfo 后返回 naive 串，函数内先归一补 'Z' 再换算——与 CLI
 * `inkflow.cli._time.format_local` 的 naive 处理同款语义（naive→按 UTC 补 tzinfo→本地）。
 */
export function formatTimestamp(iso: string): string {
  const parsed = new Date(normalizeNaiveUtc(iso));
  if (Number.isNaN(parsed.getTime())) return iso;
  const pad = (value: number) => String(value).padStart(2, '0');
  return (
    `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ` +
    `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`
  );
}

/**
 * 判定「无时区偏移的 date-time 串」并补 'Z' 归一为 UTC（ADR-055 存储口径）。
 *
 * JS 规范不一致：无偏移 date-time 串 `new Date()` 按**本地**解释，纯 date `YYYY-MM-DD`
 * 按 **UTC** 解释。故匹配到「date-time 且无偏移标记」时先补 'Z' 再解析（空格分隔
 * `str(datetime)` 形态换 'T'；带毫秒等尾缀同样归一）。纯 date（无时间部分）不加 Z——
 * JS 对其本就是 UTC 语义，加 Z 反而多余。
 *
 * 导出供需要「瞬间」而非显示串的消费方共享同一归一口径（如 ProjectCard 相对时间，
 * #1070 审查第 6 处）；纯显示消费方直接用 formatTimestamp。
 */
export function normalizeNaiveUtc(iso: string): string {
  if (!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(iso)) return iso;
  if (/(?:[Zz]|[+-]\d{2}:?\d{2})$/.test(iso)) return iso;
  return `${iso.replace(' ', 'T')}Z`;
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
