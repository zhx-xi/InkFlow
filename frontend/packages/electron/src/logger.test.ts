/**
 * F57 #888-S3 Electron 主进程 logger 契约（RED）。
 *
 * 被测模块 src/logger.ts（Codex GREEN 实现，node 环境可测、不 import electron 模块）——
 * 当前预期「Cannot find module './logger'」失败（RED）。
 *
 * 契约来源：specs/f57-logging-i18n/spec.md §1.3（GUI 日志口径含 Electron 主进程日志，
 * 经 logger 上报 /api/v1/logs 聚合进后端 loguru 同一流）+ §2.2（caller_type=frontend 结构化）。
 *
 * 主进程事件（内核启动/失败/退出/窗口关闭）由 main.ts 集成调用；本文件只测 logger 模块
 * 本身：4 方法（info/warn/error + debug）/ 结构化 record / POST /api/v1/logs / 失败兜底。
 * main.ts 集成契约由 main.*.test.ts 既有各文件（kernel-path/tray 等）守护，本文件不重复。
 *
 * 与 renderer 的差异：主进程无 window.INKFLOW_API（无 preload 注入），上报目标（baseURL+token）
 * 由 setMainLogEndpoint 显式设置（主进程从 kernelInfo 取 port+token）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createMainLogger,
  getMainLogEndpoint,
  setMainLogEndpoint,
  type MainLogger,
  type MainLogRecord,
} from './logger';

const BASE = 'http://127.0.0.1:38291';

function jsonOk() {
  return { ok: true, status: 200, json: vi.fn().mockResolvedValue({ ok: true }) } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;
let warnSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  setMainLogEndpoint('', ''); // 复位为未设置
});

afterEach(() => {
  vi.unstubAllGlobals();
  warnSpy.mockRestore();
  setMainLogEndpoint('', '');
});

describe('F57 主进程 logger：方法面', () => {
  it('createMainLogger("electron.main") 返回 debug/info/warn/error 四方法', () => {
    const logger: MainLogger = createMainLogger('electron.main');
    expect(typeof logger.debug).toBe('function');
    expect(typeof logger.info).toBe('function');
    expect(typeof logger.warn).toBe('function');
    expect(typeof logger.error).toBe('function');
  });
});

describe('F57 主进程 logger：结构化 record + 上报（POST /api/v1/logs）', () => {
  it('设置 endpoint → info(event, msgid, params) 上报 record，caller_type=frontend + caller_name + X-Correlation-Id 头', async () => {
    setMainLogEndpoint(BASE, 'kernel-tok');
    const logger = createMainLogger('electron.main');
    logger.info('kernel_ready', 'log.event.kernel_ready', { port: 38291 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE}/api/v1/logs`);
    expect(init.method).toBe('POST');
    const headers = init.headers as Headers;
    expect(headers.get('X-InkFlow-Token')).toBe('kernel-tok');
    const body = JSON.parse(init.body as string) as MainLogRecord;
    expect(body.level).toBe('info');
    expect(body.caller_type).toBe('frontend');
    expect(body.caller_name).toBe('electron.main');
    expect(body.event).toBe('kernel_ready');
    expect(body.message_key).toBe('log.event.kernel_ready');
    expect(body.params).toEqual({ port: 38291 });
    expect(typeof body.correlation_id).toBe('string');
    expect(body.correlation_id.length).toBeGreaterThan(0);
    expect(Number.isNaN(Date.parse(body.timestamp))).toBe(false);
  });

  it('warn/error → record.level 对应方法级', async () => {
    setMainLogEndpoint(BASE, 'tok');
    const logger = createMainLogger('electron.main');
    logger.warn('kernel_failure', 'log.event.kernel_failure', { attempt: 2 });
    logger.error('kernel_crash', 'log.event.kernel_crash', { code: 'EXIT_1' });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const levels = fetchMock.mock.calls.map((c) => (JSON.parse((c[1] as RequestInit).body as string) as MainLogRecord).level);
    expect(levels).toEqual(['warn', 'error']);
  });

  it('未设置 endpoint → 不 fetch，console 兜底（非阻塞），不抛', async () => {
    const logger = createMainLogger('electron.main');
    await expect(async () => logger.info('kernel_ready', 'log.event.kernel_ready')).not.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled();
  });

  it('上报失败（HTTP 500 / fetch reject）→ 不抛 + console 兜底（非阻塞）', async () => {
    setMainLogEndpoint(BASE, 'tok');
    fetchMock.mockResolvedValue({ ok: false, status: 500, json: vi.fn() } as unknown as Response);
    const logger = createMainLogger('electron.main');
    await expect(async () => logger.info('kernel_ready', 'log.event.kernel_ready')).not.toThrow();
    await vi.waitFor(() => expect(warnSpy).toHaveBeenCalled());

    warnSpy.mockClear();
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(async () => logger.warn('kernel_failure', 'log.event.kernel_failure')).not.toThrow();
    await vi.waitFor(() => expect(warnSpy).toHaveBeenCalled());
  });
});

describe('F57 主进程 logger：endpoint 设置', () => {
  it('setMainLogEndpoint 存储 baseURL+token，getMainLogEndpoint 可读回', () => {
    setMainLogEndpoint(BASE, 'tok-abc');
    expect(getMainLogEndpoint()).toEqual({ baseURL: BASE, token: 'tok-abc' });
  });

  it('空 baseURL + 空 token = 未设置（复位语义）', () => {
    setMainLogEndpoint('', '');
    expect(getMainLogEndpoint()).toEqual({ baseURL: '', token: '' });
  });
});
