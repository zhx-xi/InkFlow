/**
 * F57 #888-S3 前端 logger 契约（RED）。
 *
 * 被测模块 src/logger.ts（4 级 logger，Codex GREEN 实现）——当前预期
 * 「Cannot find module './logger'」失败（RED）。
 *
 * 契约来源：specs/f57-logging-i18n/spec.md §2.2（caller_type=frontend +
 * 结构化字段）+ 任务书 S3（4 级 logger / 上报后端 / correlation_id）。
 *
 * 结构化记录字段（与后端 LogRecordInput / api/client.ts FrontendLogRecord 对齐）：
 *   level(caller 方法级) / caller_type='frontend' / caller_name / event /
 *   message_key(=i18n msgid) / params / correlation_id / timestamp(ISO)。
 * correlation_id：页面/操作级 uuid → 请求头 X-Correlation-Id（处理在 client.ts）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createLogger, newCorrelationId, type Logger } from './logger';
import { type FrontendLogRecord } from './api/client';

// mock './api/client'：logger 只用 reportLog / getCorrelationId；真实实现
// 由后端契约测试（logging.test.ts）验证。控制 correlation_id 确定性。
const clientMock = vi.hoisted(() => ({
  reportLog: vi.fn(() => Promise.resolve()),
  getCorrelationId: vi.fn(() => 'corr-fixed'),
}));

vi.mock('./api/client', () => clientMock);

const reportLogMock = clientMock.reportLog as ReturnType<typeof vi.fn>;
const getCorrelationIdMock = clientMock.getCorrelationId as ReturnType<typeof vi.fn>;

describe('F57 前端 logger：4 级方法存在', () => {
  it('createLogger("WritingPage") 返回 debug/info/warn/error 四方法', () => {
    const logger: Logger = createLogger('WritingPage');
    expect(typeof logger.debug).toBe('function');
    expect(typeof logger.info).toBe('function');
    expect(typeof logger.warn).toBe('function');
    expect(typeof logger.error).toBe('function');
  });
});

describe('F57 前端 logger：结构化字段', () => {
  let logger: Logger;
  beforeEach(() => {
    reportLogMock.mockClear();
    getCorrelationIdMock.mockReturnValue('corr-fixed');
    logger = createLogger('WritingPage');
  });

  it('info(event, messageKey, params) → 上报 record 含全部必填结构化字段', () => {
    logger.info('create_chapter', 'log.event.create_chapter', { title: '第一章' });

    expect(reportLogMock).toHaveBeenCalledTimes(1);
    const rec = reportLogMock.mock.calls[0][0] as FrontendLogRecord;
    expect(rec.level).toBe('info');
    expect(rec.caller_type).toBe('frontend');
    expect(rec.caller_name).toBe('WritingPage');
    expect(rec.event).toBe('create_chapter');
    expect(rec.message_key).toBe('log.event.create_chapter');
    expect(rec.params).toEqual({ title: '第一章' });
    expect(rec.correlation_id).toBe('corr-fixed');
    expect(typeof rec.timestamp).toBe('string');
    expect(Number.isNaN(Date.parse(rec.timestamp))).toBe(false);
  });

  it('debug/warn/error → record.level 对应方法级（debug→debug / warn→warn / error→error）', () => {
    logger.debug('page_load', 'log.event.page_load');
    logger.warn('api_retry', 'log.event.api_retry', { attempt: 2 });
    logger.error('uncaught', 'log.event.uncaught_error', { page: 'WritingPage' });

    const recs = reportLogMock.mock.calls.map((c) => c[0] as FrontendLogRecord);
    expect(recs.map((r) => r.level)).toEqual(['debug', 'warn', 'error']);
    expect(recs[1].params).toEqual({ attempt: 2 });
    expect(recs[2].event).toBe('uncaught');
  });

  it('params 缺省 → 上报空对象（默认 {}，不缺失该字段）', () => {
    logger.info('save_chapter', 'log.event.save_chapter');
    const rec = reportLogMock.mock.calls[0][0] as FrontendLogRecord;
    expect(rec.params).toEqual({});
  });

  it('correlation_id 取当前 getCorrelationId() 值（页面/操作级关联）', () => {
    getCorrelationIdMock.mockReturnValue('page-uuid-123');
    logger.info('navigate', 'log.event.navigate');
    const rec = reportLogMock.mock.calls[0][0] as FrontendLogRecord;
    expect(rec.correlation_id).toBe('page-uuid-123');
  });

  it('console 双路输出（M1 console + 上报）：每级调用对应级别的 console 方法', () => {
    const spy = {
      debug: vi.spyOn(console, 'debug').mockImplementation(() => {}),
      info: vi.spyOn(console, 'info').mockImplementation(() => {}),
      warn: vi.spyOn(console, 'warn').mockImplementation(() => {}),
      error: vi.spyOn(console, 'error').mockImplementation(() => {}),
    };
    logger.debug('page_load', 'log.event.page_load');
    logger.info('create_chapter', 'log.event.create_chapter');
    logger.warn('api_retry', 'log.event.api_retry');
    logger.error('uncaught', 'log.event.uncaught_error');
    expect(spy.debug).toHaveBeenCalledTimes(1);
    expect(spy.info).toHaveBeenCalledTimes(1);
    expect(spy.warn).toHaveBeenCalledTimes(1);
    expect(spy.error).toHaveBeenCalledTimes(1);
    Object.values(spy).forEach((s) => s.mockRestore());
  });
});

describe('F57 前端 logger：newCorrelationId 生成 uuid', () => {
  it('返回 uuid 格式（8-4-4-4-12 十六进制）', () => {
    const id = newCorrelationId();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
  });

  it('每次调用生成不同 id（随机性）', () => {
    const a = newCorrelationId();
    const b = newCorrelationId();
    expect(a).not.toBe(b);
  });
});
