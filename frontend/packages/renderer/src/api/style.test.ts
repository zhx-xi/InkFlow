/**
 * T2 风格检测 API 契约测试（POST /api/v1/projects/{projectId}/style/analyze）
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/api/style.ts，必须导出：
 * - interface StyleWordFrequencyDto { word: string; count: number; }
 * - interface StyleFingerprintDto {
 *     sentences: number; paragraphs: number; char_count: number;
 *     sentence_avg_len: number; paragraph_avg_len: number;
 *     ellipsis_density: number; dialogue_ratio: number; vocabulary_richness: number;
 *     top_words: StyleWordFrequencyDto[];
 *   }
 * - interface StyleAITraceDto {
 *     ai_score: number; verdict: 'likely_human' | 'uncertain' | 'likely_ai';
 *     evidence: string[];
 *   }
 * - interface StyleLexicalDto { unique_words: number; total_words: number; stopword_ratio: number; }
 * - interface StyleReportDto {
 *     project_id: string; source: string;
 *     fingerprint: StyleFingerprintDto; ai_trace: StyleAITraceDto; lexical: StyleLexicalDto;
 *   }
 * - analyzeStyle(projectId: string, body: { chapter_ids?: string[]; text?: string; llm_analysis?: boolean }):
 *     Promise<StyleReportDto>
 *   → POST /api/v1/projects/{projectId}/style/analyze，body 原样透传
 *   （chapter_ids/text 至少其一由后端校验）
 *
 * 测试策略：镜像 audit.test.ts——不 mock ../api/client（避开 #107 vi.mock 闭包坑——
 * apiFetch 模块内闭包不被导出层替换影响）——直接 spy 全局 fetch，apiFetch 真实执行；
 * window.INKFLOW_API 注入固定 baseURL/token（client.test.ts 同款），URL 可精确断言。
 * 错误契约：HTTP 非 2xx → ApiError（status/detail 透传，errorMessage 可读）；
 * fetch reject（内核未启动）→ KernelOfflineError。
 *
 * RED 预期：./style 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { analyzeStyle } from './style';
import { ApiError, errorMessage, KernelOfflineError } from './client';

const BASE = 'http://api.test';

/** 契约结构镜像（GREEN 类型从 style.ts 导出；本文件内联镜像供 mock 播种） */
interface StyleWordFrequencyDto {
  word: string;
  count: number;
}

interface StyleFingerprintDto {
  sentences: number;
  paragraphs: number;
  char_count: number;
  sentence_avg_len: number;
  paragraph_avg_len: number;
  ellipsis_density: number;
  dialogue_ratio: number;
  vocabulary_richness: number;
  top_words: StyleWordFrequencyDto[];
}

interface StyleAITraceDto {
  ai_score: number;
  verdict: 'likely_human' | 'uncertain' | 'likely_ai';
  evidence: string[];
}

interface StyleLexicalDto {
  unique_words: number;
  total_words: number;
  stopword_ratio: number;
}

interface StyleReportDto {
  project_id: string;
  source: string;
  fingerprint: StyleFingerprintDto;
  ai_trace: StyleAITraceDto;
  lexical: StyleLexicalDto;
}

const reportDto: StyleReportDto = {
  project_id: 'p1',
  source: 'chapter:c1',
  fingerprint: {
    sentences: 12,
    paragraphs: 4,
    char_count: 600,
    sentence_avg_len: 22.4,
    paragraph_avg_len: 3.1,
    ellipsis_density: 0.02,
    dialogue_ratio: 0.38,
    vocabulary_richness: 0.42,
    top_words: [
      { word: '雨', count: 8 },
      { word: '城门', count: 5 },
    ],
  },
  ai_trace: {
    ai_score: 0.28,
    verdict: 'likely_human',
    evidence: ['各特征得分均低于 0.5，无明显 AI 特征'],
  },
  lexical: {
    unique_words: 120,
    total_words: 280,
    stopword_ratio: 0.12,
  },
};

/** 可控 Response 替身（audit.test.ts 同款） */
function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function setInjected(cfg: { baseURL: string; token: string } | undefined): void {
  Object.defineProperty(window, 'INKFLOW_API', {
    configurable: true,
    value: cfg,
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  setInjected({ baseURL: BASE, token: 'tok-1' });
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setInjected(undefined);
});

function lastFetchCall() {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { url, init };
}

describe('analyzeStyle — 触发风格检测', () => {
  it('chapter_ids 模式：POST style/analyze 端点，body 原样透传', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, reportDto));
    await expect(analyzeStyle('p1', { chapter_ids: ['c1'] })).resolves.toEqual(reportDto);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { url, init } = lastFetchCall();
    expect(url).toBe(`${BASE}/api/v1/projects/p1/style/analyze`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ chapter_ids: ['c1'] });
    const headers = init.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('X-InkFlow-Token')).toBe('tok-1');
  });

  it('text + llm_analysis 模式：body 透传 { text, llm_analysis: true }', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, reportDto));
    await analyzeStyle('p1', { text: '词句', llm_analysis: true });
    const { init } = lastFetchCall();
    expect(JSON.parse(init.body as string)).toEqual({ text: '词句', llm_analysis: true });
  });

  it('响应透传：完整 StyleReportDto 原样返回', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, reportDto));
    const result = await analyzeStyle('p1', { chapter_ids: ['c1'] });
    expect(result).toEqual(reportDto);
    expect(result.fingerprint.top_words).toHaveLength(2);
    expect(result.ai_trace.verdict).toBe('likely_human');
    expect(result.lexical.unique_words).toBe(120);
  });
});

describe('analyzeStyle — 错误契约', () => {
  it('HTTP 422 + detail → ApiError，errorMessage 可读', async () => {
    fetchMock.mockResolvedValue(jsonResponse(422, { detail: 'chapter_ids and text both empty' }));
    const err = await analyzeStyle('p1', {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(422);
    expect((err as ApiError).detail).toBe('chapter_ids and text both empty');
    expect(errorMessage(err)).toBe('chapter_ids and text both empty');
  });

  it('fetch reject（内核未启动）→ KernelOfflineError', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const err = await analyzeStyle('p1', { text: '词句' }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(KernelOfflineError);
    expect(errorMessage(err)).toBe('Kernel unreachable');
  });
});
