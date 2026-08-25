/** T2 风格检测（Issue #655）：触发风格分析并返回完整 StyleReport。
 * 复用 apiFetch 统一错误映射（ApiError / KernelOfflineError），不重新实现 fetch。
 */
import { apiFetch } from './client';

/** 词频条目（对齐后端 StyleWordFrequency 的 model_dump(mode='json')） */
export interface StyleWordFrequencyDto {
  word: string;
  count: number;
}

/** 风格指纹（对齐后端 StyleFingerprint 的 model_dump(mode='json')） */
export interface StyleFingerprintDto {
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

/** AI 痕迹（对齐后端 StyleAITrace 的 model_dump(mode='json')） */
export interface StyleAITraceDto {
  ai_score: number;
  verdict: 'likely_human' | 'uncertain' | 'likely_ai';
  evidence: string[];
}

/** 词汇统计（对齐后端 StyleLexical 的 model_dump(mode='json')） */
export interface StyleLexicalDto {
  unique_words: number;
  total_words: number;
  stopword_ratio: number;
}

/** 风格分析报告（对齐后端 StyleReport 的 model_dump(mode='json')） */
export interface StyleReportDto {
  project_id: string;
  source: string;
  fingerprint: StyleFingerprintDto;
  ai_trace: StyleAITraceDto;
  lexical: StyleLexicalDto;
}

/** 触发风格检测：POST /api/v1/projects/{projectId}/style/analyze（body 原样透传） */
export async function analyzeStyle(
  projectId: string,
  body: { chapter_ids?: string[]; text?: string; llm_analysis?: boolean },
): Promise<StyleReportDto> {
  return apiFetch<StyleReportDto>(`/api/v1/projects/${projectId}/style/analyze`, {
    method: 'POST',
    body,
  });
}
