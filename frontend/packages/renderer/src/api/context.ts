/**
 * #594 上下文组装 API（spec f6-context-service/gui-panel.md §2.1）：
 * POST /api/v1/context/assemble 预览上下文注入结果，前端据此渲染真实条目 + 勾选 override。
 */
import { apiFetch } from './client';

/** 上下文条目来源（7 字面量联合，与后端 Pydantic 契约对齐） */
export type ContextSourceType =
  | 'writing_requirements'
  | 'outline'
  | 'character_setting'
  | 'world_setting'
  | 'chapter_summary'
  | 'foreshadowing'
  | 'preference';

/** 单条上下文条目 */
export interface ContextItem {
  source: ContextSourceType;
  title: string;
  content: string;
  priority: number;
  metadata: Record<string, unknown>;
}

/** 组装块：条目 + 分层/预算信息 */
export interface ContextBlock {
  item: ContextItem;
  layer: string;
  token_count: number;
  compressed: boolean;
}

/** override 白名单：character_ids 非空 → 只注入命中角色；空 → 注入全部（仅过滤 character_setting/foreshadowing） */
export interface ContextOverride {
  character_ids: string[];
  foreshadowing_ids: string[];
}

/** 组装请求（writing_requirements 必填 min_length=1；max_tokens 可缺省或为 null） */
export interface AssembleContextRequest {
  project_id: string;
  chapter_id: string;
  model: string;
  writing_requirements: string;
  max_tokens?: number | null;
  override?: ContextOverride;
}

/** 被预算裁剪的条目 */
export interface ContextDropped {
  item: ContextItem;
  reason: string;
}

/** 组装结果 */
export interface ContextAssemblyResult {
  blocks: ContextBlock[];
  budget_tokens: number;
  total_tokens: number;
  model: string;
  dropped: ContextDropped[];
}

/** 预览上下文组装结果 */
export async function assembleContext(body: AssembleContextRequest): Promise<ContextAssemblyResult> {
  return apiFetch<ContextAssemblyResult>('/api/v1/context/assemble', { method: 'POST', body });
}
/** 章节摘要 DTO（Issue #656）：与后端 context.py 契约对齐 */
export interface ChapterSummaryDto {
  summary: string;
  chapter_id: string;
}

/** 获取章节摘要（GET /api/v1/context/chapters/{chapterId}/summary，后端 ensure_summary 惰性生成） */
export async function getChapterSummary(chapterId: string): Promise<ChapterSummaryDto> {
  return apiFetch<ChapterSummaryDto>(`/api/v1/context/chapters/${chapterId}/summary`);
}

/** 强制刷新章节摘要（POST /api/v1/context/chapters/{chapterId}/summary/refresh，无 body） */
export async function refreshChapterSummary(chapterId: string): Promise<ChapterSummaryDto> {
  return apiFetch<ChapterSummaryDto>(`/api/v1/context/chapters/${chapterId}/summary/refresh`, {
    method: 'POST',
  });
}
