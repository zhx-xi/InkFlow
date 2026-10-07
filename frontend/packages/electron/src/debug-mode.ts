/**
 * F51 debug-mode 判定（从 main.ts 拆出 —— #1487：main.ts 触达 monster-file 门禁 900 行，
 * 按 `ci_cd/check_file_length.py` 「超限优先拆分」规则外移；行为逐字不变）。
 *
 * 契约来源：spec f51 §7 / D1 / D6-D8；契约测试 main.kernel-gui-log.test.ts 的 DEBUG 面。
 */
import { app } from 'electron';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

/** 解析 instance.env 文本 → KEY=VALUE 映射（解析规则与 backend load_instance_env
 * 对齐：空行 / # 注释 / 无 = 行跳过；KEY/VALUE strip；空值键跳过）。 */
export function parseInstanceEnv(content: string): Record<string, string> {
  const vars: Record<string, string> = {};
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }
    const eq = line.indexOf('=');
    if (eq < 0) {
      continue;
    }
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim();
    if (key && value) {
      vars[key] = value;
    }
  }
  return vars;
}

/**
 * F51 debug-mode 统一开关：INKFLOW_DEBUG 贯穿三层（D6/D7 三层对称）。
 * 优先级（D1）：env > instance.env > config.json。
 * - env 显式设置（非空串）：'1'/'true'/'on'（trim+lowercase）→ true；'0' 等 → false 且
 *   不再读文件（显式关 > instance.env=1，D8 壳侧镜像，S3f-T1 G3）；空串=未设置（f51 §7）。
 * - instance.env 含 INKFLOW_DEBUG=1 → true；config.json "debug": true → true
 *   （data_dir = instance.env INKFLOW_DATA_DIR 优先、缺省 %APPDATA%/InkFlow）。
 * app.getPath 不可用（测试 mock）→ try/catch 返回 env 显式判定结果。
 */
export function isDebugMode(): boolean {
  const envDebug = process.env.INKFLOW_DEBUG;
  if (envDebug !== undefined && envDebug !== '') {
    // env 显式设置：'1'/'true'/'on'（不区分大小写）→ true；'0'/'false'/'off'/其他 → false，
    // 且【不再读 instance.env / config.json】（显式关 > instance.env=1，D8）
    return ['1', 'true', 'on'].includes(envDebug.trim().toLowerCase());
  }
  try {
    const appData = app.getPath('appData');
    const instanceEnvPath = path.join(appData, 'InkFlow', 'instance.env');
    const envVars = existsSync(instanceEnvPath)
      ? parseInstanceEnv(readFileSync(instanceEnvPath, 'utf8'))
      : {};
    if (envVars.INKFLOW_DEBUG === '1') {
      return true;
    }
    const dataDir = envVars.INKFLOW_DATA_DIR || path.join(appData, 'InkFlow');
    const configPath = path.join(dataDir, 'config.json');
    if (existsSync(configPath)) {
      const fileConfig = JSON.parse(readFileSync(configPath, 'utf8')) as {
        debug?: unknown;
      };
      if (fileConfig.debug === true) {
        return true;
      }
    }
  } catch {
    // getPath 不可用（测试 mock）/ 文件解析失败 → 回退 env 显式判定（等价顶部分支；重读 env
    // 规避 TS 控制流把 envDebug 收窄为 never 的编译错误）
    const catchEnvDebug = process.env.INKFLOW_DEBUG;
    return (
      catchEnvDebug !== undefined &&
      catchEnvDebug !== '' &&
      ['1', 'true', 'on'].includes(catchEnvDebug.trim().toLowerCase())
    );
  }
  return false;
}
