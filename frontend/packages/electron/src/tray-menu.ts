/**
 * 托盘菜单模板构建（#1153 / ADR-059 ④，spec f31 §5.6.1）。
 *
 * 本文件为**纯函数**（不 import electron）——`MenuItemConstructorOptions` 用最小
 * 结构形状描述，使 vitest node 环境可直接测；electron 的 `Menu.buildFromTemplate`
 * 由调用方（main.ts）注入构造结果。
 *
 * 契约来源：specs/f31-gui-tray/spec.md §5.6 / §5.6.1。
 */
import * as path from 'node:path';
import {
  formatInstanceMenuLabel,
  formatKernelMenuLabel,
  readInstanceRegistry,
  type KernelInstance,
} from './kernel';

/** 菜单项最小形状（与 Electron MenuItemConstructorOptions 兼容的子集） */
export interface TrayMenuItem {
  label?: string;
  type?: 'separator' | 'normal';
  enabled?: boolean;
  id?: string;
  click?: () => void;
}

/**
 * 读全部存活实例（#1153 / ADR-059 ④）。
 *
 * `dir` 为 null（测试 mock 无 app.getPath）或读失败 → []：托盘回落单实例形态，
 * 菜单重建绝不因注册表异常而中断。
 */
export function readLiveInstances(dir: string | null): KernelInstance[] {
  if (dir === null) {
    return [];
  }
  try {
    return readInstanceRegistry(dir);
  } catch {
    return [];
  }
}

/** 由 kernel.json 路径推出实例注册表目录（同级 running/）；无路径 → null。 */
export function registryDirFor(statePath: string | null): string | null {
  return statePath === null ? null : path.join(path.dirname(statePath), 'running');
}

export interface BuildTrayMenuOptions {
  /** kernel.json 路径（null = 测试 mock 无 getPath → 按 0 实例） */
  kernelStatePath: string | null;
  /** 当前 GUI 连接的内核（单实例形态的 label 数据源） */
  kernelInfo: { port: number; pid: number } | null;
  onOpen: () => void;
  onQuit: () => void;
}

/**
 * 构建托盘菜单模板（#1153 / ADR-059 ④，spec f31 §5.6.1）。
 *
 * - **0/1 实例**：保持既有单行「内核状态」形态（零回归，对齐 #188 F2）
 * - **≥2 实例**：渲染「内核实例 (N)」列表（用户诉求：防止不知情多开）
 *
 * `registryDir` 为 null（测试 mock 无 getPath）或读失败 → 按 0 实例处理，
 * 菜单重建绝不因注册表异常中断。
 */
export function buildTrayMenuTemplate(opts: BuildTrayMenuOptions): TrayMenuItem[] {
  const { kernelStatePath, kernelInfo, onOpen, onQuit } = opts;
  const instances = readLiveInstances(registryDirFor(kernelStatePath));

  const kernelItems: TrayMenuItem[] =
    instances.length >= 2
      ? formatInstanceMenuLabel(instances).map((label, idx) => ({
          label,
          enabled: false,
          // 首行为分组标题，其余为实例行（仅展示，不提供逐项操作）
          id: idx === 0 ? 'kernel-instances-header' : `kernel-instance-${String(idx - 1)}`,
        }))
      : [{ label: formatKernelMenuLabel(kernelInfo), enabled: false }];

  return [
    { label: '打开主窗口', click: onOpen },
    ...kernelItems,
    { type: 'separator' },
    { label: '退出', click: onQuit },
  ];
}
