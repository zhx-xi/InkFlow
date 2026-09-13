/**
 * 实例注册表消费契约（#1153 / ADR-059 ④，spec f31 §2.4 / §5.6.1）。
 *
 * 被测：src/kernel.ts 新增纯函数
 *   - readInstanceRegistry(dir: string): KernelInstance[]
 *   - formatInstanceMenuLabel(instances: KernelInstance[]): string[]
 *
 * RED 阶段：这两个导出尚不存在 → import 为 undefined → 调用抛 TypeError（预期红）。
 *
 * 契约要点（spec f31 §2.4）：
 * - 目录不存在 → []
 * - 条目需 JSON 合法 + kind ∈ {dev,rc,release} + 字段类型正确，否则跳过
 * - pid 已死的条目**不返回**，且文件被清理（惰性 GC）
 * - **不返回 token**（最小暴露面）
 * - 顺序稳定：started_at 升序，同刻按 pid
 *
 * 本文件不 import electron（可在 vitest node 环境直接运行）。
 */
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { formatInstanceMenuLabel, readInstanceRegistry } from './kernel';

let dir: string;

/** 用当前进程 pid 作「存活」样本（process.kill(pid,0) 必定成功）。 */
const ALIVE_PID = process.pid;
/** 一个几乎不可能存在的 pid（> Windows 最大 pid 常见值，且未分配 → ESRCH）。 */
const DEAD_PID = 0x7ffffff0;

function entry(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    kind: 'dev',
    port: 51234,
    token: 'tok-secret',
    pid: ALIVE_PID,
    version: '1.2.0',
    started_at: '2026-09-14T10:00:00+00:00',
    data_dir: 'C:/data/dev',
    ...over,
  };
}

function write(name: string, payload: Record<string, unknown> | string): void {
  const content = typeof payload === 'string' ? payload : JSON.stringify(payload);
  fs.writeFileSync(path.join(dir, name), content, 'utf-8');
}

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'inkflow-registry-test-'));
});

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

describe('readInstanceRegistry（spec f31 §2.4）', () => {
  it('目录不存在 → []（不抛错）', () => {
    expect(readInstanceRegistry(path.join(dir, 'nope'))).toEqual([]);
  });

  it('空目录 → []', () => {
    expect(readInstanceRegistry(dir)).toEqual([]);
  });

  it('合法条目被解析为 KernelInstance（字段完整）', () => {
    write('dev-1.json', entry());
    const got = readInstanceRegistry(dir);
    expect(got).toHaveLength(1);
    expect(got[0].kind).toBe('dev');
    expect(got[0].port).toBe(51234);
    expect(got[0].pid).toBe(ALIVE_PID);
    expect(got[0].version).toBe('1.2.0');
    expect(got[0].data_dir).toBe('C:/data/dev');
  });

  it('🔴 不返回 token（最小暴露面，spec §2.4 明文要求）', () => {
    write('dev-1.json', entry());
    const got = readInstanceRegistry(dir);
    expect(got[0]).not.toHaveProperty('token');
    expect(JSON.stringify(got)).not.toContain('tok-secret');
  });

  it('损坏 JSON 文件被跳过（不抛错）', () => {
    write('dev-bad.json', '{ not json');
    write('dev-1.json', entry());
    expect(readInstanceRegistry(dir).map((i) => i.pid)).toEqual([ALIVE_PID]);
  });

  it('缺字段条目被跳过', () => {
    write('dev-bad.json', { kind: 'dev' });
    write('dev-1.json', entry());
    expect(readInstanceRegistry(dir).map((i) => i.pid)).toEqual([ALIVE_PID]);
  });

  it('kind 非法（prod）被跳过', () => {
    write('prod-9.json', entry({ kind: 'prod', pid: ALIVE_PID + 0 }));
    write('dev-1.json', entry());
    const got = readInstanceRegistry(dir);
    expect(got).toHaveLength(1);
    expect(got[0].kind).toBe('dev');
  });

  it('pid 非数字的条目被跳过', () => {
    write('dev-bad.json', entry({ pid: 'abc' }));
    write('dev-1.json', entry());
    expect(readInstanceRegistry(dir)).toHaveLength(1);
  });

  it('🔴 pid 已死的条目不返回（存活过滤）', () => {
    write('dev-dead.json', entry({ pid: DEAD_PID }));
    write('dev-alive.json', entry());
    const got = readInstanceRegistry(dir);
    expect(got.map((i) => i.pid)).toEqual([ALIVE_PID]);
  });

  it('🔴 pid 已死的条目文件被清理（惰性 GC，无守护进程）', () => {
    const deadFile = path.join(dir, 'dev-dead.json');
    write('dev-dead.json', entry({ pid: DEAD_PID }));
    write('dev-alive.json', entry());

    readInstanceRegistry(dir);

    expect(fs.existsSync(deadFile)).toBe(false);
    // 存活条目必须保留
    expect(fs.existsSync(path.join(dir, 'dev-alive.json'))).toBe(true);
  });

  it('多 kind 条目并存（dev 多开 + rc + release）', () => {
    write('dev-1.json', entry());
    write('dev-2.json', entry({ kind: 'dev' }));
    write('rc-3.json', entry({ kind: 'rc', port: 60001 }));
    write('release-4.json', entry({ kind: 'release', port: 60002 }));
    const kinds = readInstanceRegistry(dir)
      .map((i) => i.kind)
      .sort();
    expect(kinds).toEqual(['dev', 'dev', 'rc', 'release']);
  });

  it('顺序稳定：started_at 升序', () => {
    write('dev-new.json', entry({ pid: ALIVE_PID, started_at: '2026-09-14T12:00:00+00:00' }));
    write('dev-old.json', entry({ pid: ALIVE_PID, started_at: '2026-09-14T09:00:00+00:00' }));
    const got = readInstanceRegistry(dir);
    expect(got[0].started_at).toBe('2026-09-14T09:00:00+00:00');
    expect(got[1].started_at).toBe('2026-09-14T12:00:00+00:00');
  });

  it('非 .json 文件被忽略', () => {
    fs.writeFileSync(path.join(dir, 'notes.txt'), 'hello', 'utf-8');
    write('dev-1.json', entry());
    expect(readInstanceRegistry(dir)).toHaveLength(1);
  });
});

describe('formatInstanceMenuLabel（spec f31 §5.6.1）', () => {
  it('0 实例 → 单行「未运行」（既有形态，零回归）', () => {
    expect(formatInstanceMenuLabel([])).toEqual(['内核状态: 未运行']);
  });

  it('1 实例 → 单行「运行中 (port · pid)」（既有形态，零回归）', () => {
    const label = formatInstanceMenuLabel([
      {
        kind: 'dev',
        port: 51234,
        pid: 4242,
        version: '1.2.0',
        started_at: '2026-09-14T10:00:00+00:00',
        data_dir: 'C:/data',
      },
    ]);
    expect(label).toEqual(['内核状态: 运行中 (51234 端口 · 4242 PID)']);
  });

  it('🔴 ≥2 实例 → 分组标题 + 每实例一行（用户诉求：托盘全量可见）', () => {
    const lines = formatInstanceMenuLabel([
      {
        kind: 'dev',
        port: 51234,
        pid: 4242,
        version: '1.2.0',
        started_at: '2026-09-14T10:00:00+00:00',
        data_dir: 'C:/DevData',
      },
      {
        kind: 'rc',
        port: 60001,
        pid: 5151,
        version: '1.3.0rc1',
        started_at: '2026-09-14T11:00:00+00:00',
        data_dir: 'C:/Users/me/AppData/Roaming/InkFlow',
      },
    ]);

    expect(lines[0]).toContain('内核实例');
    expect(lines[0]).toContain('2');
    expect(lines).toHaveLength(3); // 标题 + 2 行
    expect(lines[1]).toContain('dev');
    expect(lines[1]).toContain('51234');
    expect(lines[1]).toContain('4242');
    expect(lines[2]).toContain('rc');
    expect(lines[2]).toContain('60001');
  });

  it('release 显示为中文「正式」（面向用户，避免英文 jargon）', () => {
    const lines = formatInstanceMenuLabel([
      {
        kind: 'dev',
        port: 1,
        pid: 11,
        version: '1.0.0',
        started_at: '2026-09-14T10:00:00+00:00',
        data_dir: 'C:/a',
      },
      {
        kind: 'release',
        port: 2,
        pid: 22,
        version: '1.0.0',
        started_at: '2026-09-14T11:00:00+00:00',
        data_dir: 'C:/b',
      },
    ]);
    expect(lines.join('\n')).toContain('正式');
  });
});
