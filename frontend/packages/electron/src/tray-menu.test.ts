/**
 * 托盘菜单模板构建契约（#1153 / ADR-059 ④，spec f31 §5.6.1）。
 *
 * 被测：src/tray-menu.ts（纯函数，从 main.ts 抽出以满足 900 行 monster-file 门禁）
 *   - buildTrayMenuTemplate({ kernelStatePath, kernelInfo, onOpen, onQuit })
 *   - registryDirFor(statePath)
 *
 * 关键回归契约：0/1 实例时菜单形态必须与 #188 F2 既有形态**完全一致**
 * （label 文案 + 项序），否则既有托盘 E2E/单测会红。
 */
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildTrayMenuTemplate, registryDirFor } from './tray-menu';

let tmp: string;
const ALIVE_PID = process.pid;

function writeInstance(kind: string, port: number): void {
  const dir = path.join(tmp, 'running');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, `${kind}-${String(ALIVE_PID)}-${String(port)}.json`),
    JSON.stringify({
      kind,
      port,
      token: 'tok',
      pid: ALIVE_PID,
      version: '1.0.0',
      started_at: '2026-09-14T10:00:00+00:00',
      data_dir: 'C:/d',
    }),
    'utf-8'
  );
}

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'inkflow-traymenu-'));
});

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

describe('registryDirFor（kernel.json 路径 → 注册表目录）', () => {
  it('null → null', () => {
    expect(registryDirFor(null)).toBeNull();
  });

  it('kernel.json 路径 → 同级 running/ 目录', () => {
    expect(registryDirFor(path.join('C:', 'app', 'kernel.json'))).toBe(
      path.join('C:', 'app', 'running')
    );
  });
});

describe('buildTrayMenuTemplate（spec §5.6.1 渲染规则）', () => {
  const noop = (): void => undefined;

  it('🔴 0 实例：三项菜单（打开 / 未运行 / 退出），既有形态零回归', () => {
    const t = buildTrayMenuTemplate({
      kernelStatePath: path.join(tmp, 'kernel.json'),
      kernelInfo: null,
      onOpen: noop,
      onQuit: noop,
    });
    expect(t.map((i) => i.label ?? i.type)).toEqual([
      '打开主窗口',
      '内核状态: 未运行',
      'separator',
      '退出',
    ]);
  });

  it('🔴 1 实例：单行「运行中 (port · pid)」形态（既有 #188 F2 文案逐字一致）', () => {
    const t = buildTrayMenuTemplate({
      kernelStatePath: path.join(tmp, 'kernel.json'),
      kernelInfo: { port: 51234, pid: 4242 },
      onOpen: noop,
      onQuit: noop,
    });
    expect(t[1].label).toBe('内核状态: 运行中 (51234 端口 · 4242 PID)');
    expect(t).toHaveLength(4); // 打开 / 状态 / 分隔 / 退出
  });

  it('🔴 ≥2 实例：分组标题 + 每实例一行（用户诉求：托盘全量可见）', () => {
    writeInstance('dev', 51234);
    writeInstance('rc', 60001);

    const t = buildTrayMenuTemplate({
      kernelStatePath: path.join(tmp, 'kernel.json'),
      kernelInfo: { port: 51234, pid: ALIVE_PID },
      onOpen: noop,
      onQuit: noop,
    });

    const labels = t.map((i) => i.label ?? i.type);
    expect(labels[0]).toBe('打开主窗口');
    expect(labels[1]).toContain('内核实例');
    expect(labels[1]).toContain('2');
    expect(labels[2]).toContain('dev');
    expect(labels[3]).toContain('rc');
    expect(labels.at(-1)).toBe('退出');
  });

  it('注册表目录不可用（kernelStatePath=null）→ 按 0 实例（不抛错）', () => {
    const t = buildTrayMenuTemplate({
      kernelStatePath: null,
      kernelInfo: null,
      onOpen: noop,
      onQuit: noop,
    });
    expect(t[1].label).toBe('内核状态: 未运行');
  });

  it('注册表目录不存在 → 按 0 实例（不抛错）', () => {
    const t = buildTrayMenuTemplate({
      kernelStatePath: path.join(tmp, 'nowhere', 'kernel.json'),
      kernelInfo: null,
      onOpen: noop,
      onQuit: noop,
    });
    expect(t[1].label).toBe('内核状态: 未运行');
  });

  it('实例条目均为只读（enabled=false）；点击回调仅「打开/退出」绑定', () => {
    writeInstance('dev', 1);
    writeInstance('rc', 2);
    const onOpen = vi.fn();
    const onQuit = vi.fn();

    const t = buildTrayMenuTemplate({
      kernelStatePath: path.join(tmp, 'kernel.json'),
      kernelInfo: null,
      onOpen,
      onQuit,
    });

    // 实例区各项：只读、无 click
    for (const item of t.slice(1, 4)) {
      expect(item.enabled).toBe(false);
      expect(item.click).toBeUndefined();
    }
    t[0].click?.();
    t.at(-1)?.click?.();
    expect(onOpen).toHaveBeenCalledOnce();
    expect(onQuit).toHaveBeenCalledOnce();
  });

  it('实例行 id 递增且分组标题 id 固定（供未来逐项操作定位）', () => {
    writeInstance('dev', 1);
    writeInstance('rc', 2);
    const t = buildTrayMenuTemplate({
      kernelStatePath: path.join(tmp, 'kernel.json'),
      kernelInfo: null,
      onOpen: noop,
      onQuit: noop,
    });
    expect(t[1].id).toBe('kernel-instances-header');
    expect(t[2].id).toBe('kernel-instance-0');
    expect(t[3].id).toBe('kernel-instance-1');
  });
});
