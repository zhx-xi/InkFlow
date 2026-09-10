/**
 * #936 C 项探测门禁判据（纯函数，独立模块便于单测 + 满足 fast-refresh 约束）。
 *
 * 与后端契约 §3.3 对齐：保存前探测失败 → HTTP 422，detail 含模型 id + 失败摘要
 * + 「如需强制保存请使用 force=true」。GUI 据此判定是否引导用户走强制保存逃生门。
 */

/**
 * 判定错误是否为「保存前探测门禁拒绝」（可强制保存）。
 *
 * 判据：HTTP 422 **且** detail 含 `force=true` 提示。
 * 只有门禁拒绝才引导强制保存；其他 422（如字段校验失败）/ 非 422 一律 false，
 * 避免误判（如 500 或普通校验错误也弹「强制保存」框）。
 */
export function isForceableProbeRejection(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  const status = (err as { status?: unknown }).status;
  if (status !== 422) return false;
  const detail = (err as { detail?: unknown }).detail;
  const text = typeof detail === 'string' ? detail : err.message;
  return text.includes('force=true');
}
