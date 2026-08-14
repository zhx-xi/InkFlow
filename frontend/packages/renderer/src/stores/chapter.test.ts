/**
 * chapter store 测试契约（Issue #79 RED 阶段，spec §4.2.1 / §4.4）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须匹配以下导出/签名：
 *
 * 新增 REST actions（当前骨架缺失 → RED）：
 * - loadChapterTree(projectId: string): Promise<void>
 *     GET /api/v1/projects/{projectId}/volumes → {items: Volume[]}（后端统一分页/列表包装契约，2026-08-05 评审 L1 修正）
 *     GET /api/v1/projects/{projectId}/chapters → {items: Chapter[]}（含 word_count）
 *     → setTree(volumes, chapters)
 * - selectChapter(chapterId: string): Promise<void>
 *     GET /api/v1/chapters/{chapterId} → Chapter（含 content）
 *     → setCurrentChapter(id) + setContent(chapter.content)
 * - saveContent(): Promise<void>  —— 自动保存（Ctrl+S / 防抖自动保存入口）
 *     PATCH /api/v1/chapters/{currentChapterId}，body {content: 当前 store.content}
 *     未选中章节（currentChapterId null）时静默跳过（不发请求）
 * - createChapter(projectId: string, title: string, volumeId?: string): Promise<ChapterMeta>
 *     POST /api/v1/projects/{projectId}/chapters（201）→ 追加到 chapters 并选中新章节
 *
 * 既有骨架 actions（setTree/setCurrentChapter/setContent/setLoading/setError）保持签名不变。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useChapterStore } from './chapter';
import { apiFetch } from '../api/client';
import type { ChapterMeta, Volume } from './chapter';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const volumes: Volume[] = [
  { id: 'v1', title: '第一卷 风起', order_index: 0 },
  { id: 'v2', title: '第二卷 云涌', order_index: 1 },
];

const chapters: ChapterMeta[] = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  useChapterStore.setState({
    volumes: [], chapters: [], currentChapterId: null, content: '', loading: false, error: null,
  });
});

describe('chapter store — 契约面（GREEN 必须提供）', () => {
  it('暴露 REST actions: loadChapterTree / selectChapter / saveContent / createChapter', () => {
    const s = useChapterStore.getState();
    expect(typeof s.loadChapterTree).toBe('function');
    expect(typeof s.selectChapter).toBe('function');
    expect(typeof s.saveContent).toBe('function');
    expect(typeof s.createChapter).toBe('function');
  });
});

describe('chapter store — 卷章树与当前章', () => {
  it('初始状态：空树 / 无当前章 / 空正文', () => {
    const s = useChapterStore.getState();
    expect(s.volumes).toEqual([]);
    expect(s.chapters).toEqual([]);
    expect(s.currentChapterId).toBeNull();
    expect(s.content).toBe('');
  });

  it('loadChapterTree：拉取卷 + 章列表填充树', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects/p1/volumes') return { items: volumes };
      if (path === '/api/v1/projects/p1/chapters') return { items: chapters, total: 2, offset: 0, limit: 50 };
      throw new Error(`unexpected path: ${path}`);
    });

    await act(async () => {
      await useChapterStore.getState().loadChapterTree('p1');
    });

    const s = useChapterStore.getState();
    expect(s.volumes).toEqual(volumes);
    expect(s.chapters).toEqual(chapters);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('loadChapterTree 失败：error 记录 + loading 复位', async () => {
    apiFetchMock.mockRejectedValue(new Error('章节列表获取失败'));
    await act(async () => {
      await useChapterStore.getState().loadChapterTree('p1');
    });
    expect(useChapterStore.getState().error).toContain('章节列表获取失败');
    expect(useChapterStore.getState().loading).toBe(false);
  });

  it('#345: loadChapterTree 切项目时重置当前章与正文（防旧项目 content 残留）', async () => {
    // 模拟项目 A 状态：已选中章节 + 正文（树已加载，treeProjectId='p1'）
    useChapterStore.setState({ treeProjectId: 'p1', currentChapterId: 'c1', content: '项目 A 的正文' });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects/p2/volumes') return { items: volumes };
      if (path === '/api/v1/projects/p2/chapters') return { items: chapters, total: 2, offset: 0, limit: 50 };
      throw new Error(`unexpected path: ${path}`);
    });

    await act(async () => {
      await useChapterStore.getState().loadChapterTree('p2');
    });
    const s = useChapterStore.getState();
    // 切到项目 B：正文与当前章必须清空，绝不允许显示上一项目的文字
    expect(s.content).toBe('');
    expect(s.currentChapterId).toBeNull();
    expect(s.treeProjectId).toBe('p2');
    expect(s.volumes).toEqual(volumes);
    expect(s.chapters).toEqual(chapters);
  });

  it('#371: loadChapterTree 同项目 reload 保留当前章与正文（防挂载清空已播种/已编辑内容）', async () => {
    // 模拟同项目刷新场景：树已属于 p1 + 已选中章节 + 正文（写作页挂载自动 reload）
    useChapterStore.setState({ treeProjectId: 'p1', currentChapterId: 'c1', content: '已有正文第一段。' });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects/p1/volumes') return { items: volumes };
      if (path === '/api/v1/projects/p1/chapters') return { items: chapters, total: 2, offset: 0, limit: 50 };
      throw new Error(`unexpected path: ${path}`);
    });

    await act(async () => {
      await useChapterStore.getState().loadChapterTree('p1');
    });
    const s = useChapterStore.getState();
    // 同项目 reload：正文与当前章保留（#371 修复：不再无条件清空）
    expect(s.content).toBe('已有正文第一段。');
    expect(s.currentChapterId).toBe('c1');
    expect(s.volumes).toEqual(volumes);
    expect(s.chapters).toEqual(chapters);
  });

  it('selectChapter：GET /chapters/{id} → 当前章 + 正文段落化纯文本提交', async () => {
    apiFetchMock.mockResolvedValue({
      id: 'c1', project_id: 'p1', volume_id: 'v1', title: '第1章 初见',
      content: '第一章正文第一段。\n\n第一章正文第二段。', word_count: 2347, order_index: 0,
    });
    await act(async () => {
      await useChapterStore.getState().selectChapter('c1');
    });
    const s = useChapterStore.getState();
    expect(s.currentChapterId).toBe('c1');
    expect(s.content).toContain('第一章正文第一段');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/chapters/c1', undefined);
  });

  it('saveContent：PATCH /chapters/{currentChapterId}，body 携带当前正文', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    useChapterStore.setState({ currentChapterId: 'c2', content: '修改后的正文' });
    await act(async () => {
      await useChapterStore.getState().saveContent();
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/chapters/c2', {
      method: 'PATCH',
      body: { content: '修改后的正文' },
    });
  });

  it('saveContent：未选中章节时静默跳过（不发请求）', async () => {
    useChapterStore.setState({ currentChapterId: null, content: '正文' });
    await act(async () => {
      await useChapterStore.getState().saveContent();
    });
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it('createChapter：POST /projects/{id}/chapters → 追加并选中新章节', async () => {
    const created: ChapterMeta = { id: 'c9', title: '第3章 别离', volume_id: 'v1', order_index: 2, word_count: 0 };
    apiFetchMock.mockResolvedValue(created);
    await act(async () => {
      await useChapterStore.getState().createChapter('p1', '第3章 别离', 'v1');
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1/chapters', {
      method: 'POST',
      body: { title: '第3章 别离', volume_id: 'v1' },
    });
    const s = useChapterStore.getState();
    expect(s.chapters).toContainEqual(created);
    expect(s.currentChapterId).toBe('c9');
  });

  it('setContent：SSE done 帧一次性提交入口（§4.5 store 边界）', () => {
    act(() => {
      useChapterStore.getState().setContent('流式生成的完整正文');
    });
    expect(useChapterStore.getState().content).toBe('流式生成的完整正文');
  });
});

/**
 * #105 Coverage-Gap 补测（非 RED）：selectChapter 失败 catch 分支（L87-88）
 * + 四个基础 setter 函数调用面（setTree/setCurrentChapter/setLoading/setError）。
 */
describe('chapter store — 失败兜底与 setter 组（#105 补测）', () => {
  it('selectChapter 失败：error 记录 + loading 复位（catch 分支）', async () => {
    apiFetchMock.mockRejectedValue(new Error('章节详情获取失败'));
    await act(async () => {
      await useChapterStore.getState().selectChapter('c1');
    });
    const s = useChapterStore.getState();
    expect(s.error).toContain('章节详情获取失败');
    expect(s.loading).toBe(false);
    expect(s.currentChapterId).toBeNull();
  });

  it('setter 组：setTree / setCurrentChapter / setLoading / setError 同步状态', () => {
    act(() => {
      const s = useChapterStore.getState();
      s.setTree(volumes, chapters);
      s.setCurrentChapter('c2');
      s.setLoading(true);
      s.setError('临时错误');
    });
    const s = useChapterStore.getState();
    expect(s.volumes).toEqual(volumes);
    expect(s.chapters).toEqual(chapters);
    expect(s.currentChapterId).toBe('c2');
    expect(s.loading).toBe(true);
    expect(s.error).toBe('临时错误');
  });
});
