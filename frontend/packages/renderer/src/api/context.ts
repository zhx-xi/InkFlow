/**
 * #594 上下文组装 API（spec f6-context/gui-panel.md §2.1）：
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

/** override 白名单（#1235）：显式数组 = 只注入命中项，空数组 = 删空（不注入）；缺省/null = 注入全部 */
export interface ContextOverride {
  character_ids: string[];
  foreshadowing_ids: string[];
  world_ids: string[];
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

/** 世界观条目列表行（#704：选择注入搜索选择器数据源） */
export interface WorldSettingItem {
  id: string;
  name: string;
  category: string;
}

/** GET /api/v1/projects/{projectId}/world-settings——项目世界观条目列表 */
export async function listProjectWorldSettings(
  projectId: string,
): Promise<{ items: WorldSettingItem[]; total: number; offset: number; limit: number }> {
  return apiFetch(`/api/v1/projects/${projectId}/world-settings`);
}

/** 伏笔条目列表行（#704：选择注入搜索选择器数据源） */
export interface ForeshadowingItem {
  id: string;
  title: string;
  status: string;
  priority: number;
  location: string;
}

/** GET /api/v1/projects/{projectId}/foreshadowings——项目伏笔列表 */
export async function listProjectForeshadowings(
  projectId: string,
): Promise<{ items: ForeshadowingItem[]; total: number; offset: number; limit: number }> {
  return apiFetch(`/api/v1/projects/${projectId}/foreshadowings`);
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

/** #1349 章级注入记录（回执面）：本次生成**实际**注入了哪些设定条目 id */
export interface ChapterInjectionDto {
  chapter_id: string;
  /** 产生该明细的执行记录 id；无记录时为 null */
  execution_id: string | null;
  /** 三源 id 明细；无记录时为 null（前端据此回退 assemble 预览态） */
  injected_context: ContextOverride | null;
}

/** 章级注入记录回读（GET /api/v1/agent/chapters/{chapterId}/injections） */
export async function fetchChapterInjections(chapterId: string): Promise<ChapterInjectionDto> {
  return apiFetch<ChapterInjectionDto>(`/api/v1/agent/chapters/${chapterId}/injections`);
}

/** #1379 预选请求：进入空章时按本章大纲预挑相关条目（输入面与 assemble 同口径） */
export interface PreselectContextRequest {
  project_id: string;
  chapter_id: string;
  model: string;
  writing_requirements: string;
}

/**
 * #1379 预选结果（POST /api/v1/context/preselect）：
 * `mode="agent"` = LLM 按大纲预选出的三类 id 子集；
 * `mode="fallback"` = 回退全选（无大纲 / 预选失败），此时三类即全量候选。
 */
export interface ContextPreselectResult {
  character_ids: string[];
  world_ids: string[];
  foreshadowing_ids: string[];
  mode: 'agent' | 'fallback';
}

/** 按本章大纲预选相关条目（失败/不可用 → 调用方回退全选） */
export async function preselectContext(
  body: PreselectContextRequest,
): Promise<ContextPreselectResult> {
  return apiFetch<ContextPreselectResult>('/api/v1/context/preselect', { method: 'POST', body });
}
