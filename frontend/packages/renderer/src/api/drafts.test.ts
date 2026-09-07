/**
 * 草稿审批 API 契约测试（T1 草稿审批 + #988 source_outline_id 扩展）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须匹配 src/api/drafts.ts：
 *
 * export interface DraftDto {
 *   id: string; project_id: string; chapter_id: string | null;
 *   agent_run_id: string | null; content: string; status: string; // 'draft'|'confirmed'|'rejected'
 *   summary: string; created_at: string; confirmed_at: string | null;
 *   volume_id?: string | null;           // #976 卷归组
 *   source_outline_id?: string | null;   // #988 来源大纲章节点（创建时记录）
 * }
 * export async function listDrafts(projectId: string, status?: string): Promise<{ items: DraftDto[]; total: number }>
 *   → GET /api/v1/agent/drafts?project_id=<projectId>
 * export async function confirmDraft(
 *   draftId: string,
 *   options?: { chapterId?: string; sourceOutlineId?: string; title?: string },
 * ): Promise<{ draft_id: string; status: string; chapter_id: string | null }>
 *   → POST /api/v1/agent/drafts/{draftId}/confirm
 *   body 装配（#988 契约升级：第二参从位置 chapterId 迁移为 options 对象）:
 *     options 缺省 → {}；chapterId → chapter_id；sourceOutlineId → source_outline_id；
 *     title → title；仅传出现的键（undefined 键不落 body）。
 * export async function rejectDraft(draftId: string): Promise<{ draft_id: string; status: string }>
 *   → POST /api/v1/agent/drafts/{draftId}/reject（无 body）
 * export async function updateDraft(draftId: string, content: string): Promise<{ draft_id: string; status: string; word_count: number; learned: boolean }>
 *   → PATCH /api/v1/agent/drafts/{draftId}  body: { content }
 * export async function pruneOrphans(dryRun = false): Promise<{ deleted: number }>
 *   → POST /api/v1/agent/drafts/prune-orphans  body: { dry_run: dryRun }
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { listDrafts, confirmDraft, rejectDraft, updateDraft, pruneOrphans } from './drafts';
import { apiFetch } from './client';

vi.mock('./client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
});

/** 与后端 DTO 对齐的完整草稿对象（status='draft'，chapter_id=null，#988 含来源锚） */
const draftDto = {
  id: 'd1',
  project_id: 'p1',
  chapter_id: null,
  agent_run_id: 'r1',
  content: 'AI 生成的章节草稿正文',
  status: 'draft',
  summary: '第3章 渡口夜雾',
  created_at: '2026-08-25T10:00:00Z',
  confirmed_at: null,
  source_outline_id: 'o1',
};

describe('drafts API — listDrafts（项目草稿列表）', () => {
  it('按 project_id 查询 → GET /api/v1/agent/drafts?project_id=<id>', async () => {
    apiFetchMock.mockResolvedValue({ items: [], total: 0 } as never);
    await listDrafts('p1');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts?project_id=p1');
  });

  it('返回 {items, total}（完整 DraftDto，含 #988 source_outline_id 透传）', async () => {
    const resp = { items: [draftDto], total: 1 };
    apiFetchMock.mockResolvedValue(resp as never);
    const out = await listDrafts('p1');
    expect(out).toEqual(resp);
    // DraftDto 编译面契约：source_outline_id 可空字段存在（tsc 门禁共同锁定）
    expect(out.items[0].source_outline_id).toBe('o1');
  });

  it('未记录来源草稿（#988 存量行）→ source_outline_id 为 null/缺省均可', async () => {
    const legacy = { ...draftDto, id: 'd2', source_outline_id: null };
    apiFetchMock.mockResolvedValue({ items: [legacy], total: 1 } as never);
    const out = await listDrafts('p1');
    expect(out.items[0].source_outline_id).toBeNull();
  });
});

describe('drafts API — confirmDraft（确认草稿，#988 options 签名）', () => {
  it('无 options → POST confirm + body {}（既有形态零回归）', async () => {
    apiFetchMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null } as never);
    await confirmDraft('d1');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts/d1/confirm', {
      method: 'POST',
      body: {},
    });
  });

  it('options.chapterId → body {chapter_id}（位置参契约迁移为 options 键）', async () => {
    apiFetchMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: 'c1' } as never);
    await confirmDraft('d1', { chapterId: 'c1' });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts/d1/confirm', {
      method: 'POST',
      body: { chapter_id: 'c1' },
    });
  });

  it('【R】options.sourceOutlineId → body {source_outline_id}（#988 D4 回填主通道）', async () => {
    apiFetchMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null } as never);
    await confirmDraft('d1', { sourceOutlineId: 'o1' });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts/d1/confirm', {
      method: 'POST',
      body: { source_outline_id: 'o1' },
    });
  });

  it('【R】options.title → body {title}（自动建章显式标题）', async () => {
    apiFetchMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: null } as never);
    await confirmDraft('d1', { title: '自定义标题' });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts/d1/confirm', {
      method: 'POST',
      body: { title: '自定义标题' },
    });
  });

  it('【R】三键同传 → body 齐载（仅出现的键入 body）', async () => {
    apiFetchMock.mockResolvedValue({ draft_id: 'd1', status: 'confirmed', chapter_id: 'c1' } as never);
    await confirmDraft('d1', { chapterId: 'c1', sourceOutlineId: 'o1', title: 'T' });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts/d1/confirm', {
      method: 'POST',
      body: { chapter_id: 'c1', source_outline_id: 'o1', title: 'T' },
    });
  });

  it('返回确认结果 DTO', async () => {
    const resp = { draft_id: 'd1', status: 'confirmed', chapter_id: null };
    apiFetchMock.mockResolvedValue(resp as never);
    await expect(confirmDraft('d1')).resolves.toEqual(resp);
  });
});

describe('drafts API — rejectDraft（驳回草稿）', () => {
  it('→ POST /api/v1/agent/drafts/{id}/reject（无 body）', async () => {
    apiFetchMock.mockResolvedValue({ draft_id: 'd1', status: 'rejected' } as never);
    await rejectDraft('d1');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts/d1/reject', { method: 'POST' });
  });

  it('返回驳回结果 DTO', async () => {
    const resp = { draft_id: 'd1', status: 'rejected' };
    apiFetchMock.mockResolvedValue(resp as never);
    await expect(rejectDraft('d1')).resolves.toEqual(resp);
  });
});

describe('drafts API — updateDraft（编辑草稿正文）', () => {
  it('→ PATCH /api/v1/agent/drafts/{id} + body {content}', async () => {
    apiFetchMock.mockResolvedValue({
      draft_id: 'd1',
      status: 'draft',
      word_count: 120,
      learned: true,
    } as never);
    await updateDraft('d1', '新内容');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts/d1', {
      method: 'PATCH',
      body: { content: '新内容' },
    });
  });

  it('返回 {draft_id, status, word_count, learned}', async () => {
    const resp = { draft_id: 'd1', status: 'draft', word_count: 120, learned: true };
    apiFetchMock.mockResolvedValue(resp as never);
    await expect(updateDraft('d1', '新内容')).resolves.toEqual(resp);
  });
});

describe('drafts API — pruneOrphans（清理孤儿草稿）', () => {
  it('默认 dryRun=false → POST prune-orphans + body {dry_run:false}', async () => {
    apiFetchMock.mockResolvedValue({ deleted: 0 } as never);
    await pruneOrphans();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts/prune-orphans', {
      method: 'POST',
      body: { dry_run: false },
    });
  });

  it('dryRun=true → body {dry_run:true}', async () => {
    apiFetchMock.mockResolvedValue({ deleted: 3 } as never);
    await pruneOrphans(true);
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/drafts/prune-orphans', {
      method: 'POST',
      body: { dry_run: true },
    });
  });

  it('返回 {deleted}', async () => {
    const resp = { deleted: 2 };
    apiFetchMock.mockResolvedValue(resp as never);
    await expect(pruneOrphans()).resolves.toEqual(resp);
  });
});
