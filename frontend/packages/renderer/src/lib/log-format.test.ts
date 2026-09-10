/**
 * #1000 时间显示本地化 RED 契约（ADR-055：存储 UTC / 显示本地）。
 *
 * setup.ts 钉 TZ=Asia/Shanghai：以下所有「本地时间」断言以 +08:00 为确定基准，
 * 与 runner/CI 系统时区解耦（Node 运行时 TZ 即时生效，探针实证）。
 *
 * 契约：
 * - formatTimestamp：ISO → 系统本地时区 'YYYY-MM-DD HH:mm:ss'（本地访问器手拼，
 *   勿用 toLocaleString —— 12/24 小时制与 locale 差异会破坏契约）；
 *   Z 后缀 UTC 输入按本地偏移换算（+08:00 基准 = +8h，跨日进位）；
 *   带偏移输入换算到本地基准；解析失败原样直出。
 * - formatClock：formatTimestamp 的时间部分（本地 'HH:mm:ss'，#932 链节点简式）。
 */
import { describe, expect, it } from 'vitest';
import { formatClock, formatTimestamp } from './log-format';

describe('formatTimestamp — #1000 本地时区显示', () => {
  it('UTC Z 后缀输入 → 换算到本地（+08:00 基准 = +8h）', () => {
    expect(formatTimestamp('2026-09-04T01:00:00.000Z')).toBe('2026-09-04 09:00:00');
  });

  it('跨日进位：23:30Z → 次日 07:30 本地', () => {
    expect(formatTimestamp('2026-09-04T23:30:00Z')).toBe('2026-09-05 07:30:00');
  });

  it('带 +08:00 偏移输入 → 与基准一致原值（换算回同一瞬间）', () => {
    expect(formatTimestamp('2026-09-04T01:02:03.456+08:00')).toBe('2026-09-04 01:02:03');
  });

  it('负偏移输入 -05:00 → 换算到 +08:00 基准（+13h）', () => {
    expect(formatTimestamp('2026-09-04T00:00:00-05:00')).toBe('2026-09-04 13:00:00');
  });

  it('毫秒截断到秒（不进位）', () => {
    expect(formatTimestamp('2026-09-04T01:00:00.987Z')).toBe('2026-09-04 09:00:00');
  });

  it('解析失败原样直出（#496 既有契约保留）', () => {
    expect(formatTimestamp('not-a-date')).toBe('not-a-date');
  });

  it('#1069 naive date-time 串 = UTC 存储口径：归一后换算（禁按本地误释）', () => {
    // 实体端点经 SQLite DateTime 剥 tzinfo → naive 串（值=UTC，ADR-055）。
    // JS new Date('...T08:00:00') 无偏移按本地解释（TZ=+8 → 08:00 本地）——BUG；
    // 正确 = 先补 Z（UTC）再转本地 = 16:00:00。
    expect(formatTimestamp('2026-08-10T08:00:00')).toBe('2026-08-10 16:00:00');
    // 与等价 Z 输入同瞬间（naive 归一后两形态结果必须一致）
    expect(formatTimestamp('2026-09-04T01:00:00')).toBe(formatTimestamp('2026-09-04T01:00:00Z'));
  });

  it('#1069 空格分隔 naive 串（str(datetime) 形态）同样归一', () => {
    expect(formatTimestamp('2026-08-10 08:00:00')).toBe('2026-08-10 16:00:00');
  });
});

describe('formatClock — #1000 本地时区简式时钟', () => {
  it("链节点契约：'2026-09-04T00:01:00Z' → 本地 '08:01:00'", () => {
    expect(formatClock('2026-09-04T00:01:00Z')).toBe('08:01:00');
  });

  it('与 formatTimestamp 时间部分一致（同一实现口径）', () => {
    const iso = '2026-09-04T18:30:00Z';
    expect(formatClock(iso)).toBe(formatTimestamp(iso).slice(11, 19));
  });
});
