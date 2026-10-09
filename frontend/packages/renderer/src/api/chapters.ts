/**
 * #1407：章节列表「翻全量」helper（4 处消费点的唯一实现）。
 *
 * 根因：后端 `GET /api/v1/projects/{pid}/chapters` 是**分页端点**
 * （默认 limit=50、上限 100；响应 {items,total,offset,limit}，
 * 见 backend/src/inkflow/api/routers/chapter.py）→ 前端裸请求只拿第一页，
 * >50 章项目在「写作页左栏卷章树 / 项目页卡片进度 / AI 提取章节下拉」三处被静默截断。
 *
 * 与 #1374 同族（该单在 useOutlineLibrary 内联翻页修了章标题映射一处）；
 * 本 helper 收敛 4 处消费点（含 #1374 那处改为复用，去除重复实现）。
 */
import { apiFetch } from './client';

/** 章节列表项（镜像 useChapterStore ChapterMeta） */
export interface ChapterListDto {
  id: string;
  title: string;
  volume_id: string | null;
  order_index: number;
  word_count: number;
  /** #1440：被 `book run --force` 覆盖前的旧正文（后端响应项透传；缺省 = 无上一稿） */
  previous_content?: string | null;
  writing_requirements?: string | null;
}

/** 分页端点响应（后端恒有 total/offset/limit；此处可选以便旧 mock 兼容） */
export interface ChapterListResponse {
  items?: ChapterListDto[];
  total?: number;
  offset?: number;
  limit?: number;
}

/** 续页单页上限（后端 limit 最大 100） */
export const CHAPTER_FULL_LIMIT = 100;

/**
 * 取满项目全量章节（首页不带 query 保持既有端点形状；续页 offset 步进）。
 *
 * - 首页无 query → 后端默认 50/页（既有 mock / 调用面按此形状）
 * - 续页 `?offset=<已取条数>&limit=100`，累计 >= total 即停（整页倍数不多发请求）
 * - `total` 缺失 → 按单页收口；续页空 items → 立即停止（防 total 虚高死循环）
 * - 返回 `total` 一律为**响应体口径**（项目卡片进度分母用服务端全量，非页内条数）
 */
export async function fetchAllChapters(
  projectId: string,
): Promise<{ items: ChapterListDto[]; total: number }> {
  const first = await apiFetch<ChapterListResponse>(`/api/v1/projects/${projectId}/chapters`);
  const items = [...(first.items ?? [])];
  const total = first.total ?? items.length;
  while (items.length > 0 && items.length < total) {
    const next = await apiFetch<ChapterListResponse>(
      `/api/v1/projects/${projectId}/chapters?offset=${items.length}&limit=${CHAPTER_FULL_LIMIT}`,
    );
    const page = next.items ?? [];
    if (page.length === 0) break;
    items.push(...page);
  }
  return { items, total };
}

/** 恢复上一稿响应（章 JSON；content 与 previous_content 互换后的值） */
export interface ChapterRestoreDto {
  id: string;
  title: string;
  volume_id: string | null;
  order_index: number;
  word_count: number;
  content: string;
  previous_content: string | null;
  writing_requirements?: string | null;
}

/**
 * #1440：恢复上一稿（POST /api/v1/chapters/{id}/restore-previous，**无请求体**）。
 *
 * 后端语义：`previous_content` 写回 `content` ⇒ 两者**互换**（可再调一次切回）。
 * 错误由 apiFetch 抛 ApiError：404「章节不存在」/ 409「无可恢复的旧稿」。
 */
export async function restorePreviousContent(chapterId: string): Promise<ChapterRestoreDto> {
  return apiFetch<ChapterRestoreDto>(`/api/v1/chapters/${chapterId}/restore-previous`, {
    method: 'POST',
  });
}

/** 卷列表项（镜像 GET /projects/{pid}/volumes 响应项） */
export interface VolumeListDto {
  id: string;
  project_id: string;
  title: string;
  order_index?: number;
}

/** 卷列表响应（后端恒有 items；与 ChapterListResponse 同形） */
export interface VolumeListResponse {
  items: VolumeListDto[];
}

/**
 * #1544：取项目卷列表（GET /api/v1/projects/{projectId}/volumes）。
 *
 * AI 提取对话框「按卷」范围用：卷 → 章由章节的 `volume_id` 归并（见 AIExtractDialog）。
 * 后端返回 {items:[...]}（无分页），失败由 apiFetch 抛 ApiError。
 */
export async function fetchVolumes(projectId: string): Promise<VolumeListResponse> {
  return apiFetch<VolumeListResponse>(`/api/v1/projects/${projectId}/volumes`);
}
