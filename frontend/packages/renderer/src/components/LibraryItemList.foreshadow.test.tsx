/**
 * ⚠️ 契约文件（Issue #1324：伏笔行未渲染状态/优先级/位置）
 *
 * 【背景】设计基准 `design/GUI/foreshadow/foreshadow.html:221-265` 每行渲染 4 字段
 * （标题 / 状态徽标 / 优先级 / 位置徽标 + 悬停操作），后端 `GET /projects/{pid}/foreshadowings`
 * 已全量返回 status/priority/location/resolved_at（`api/routers/foreshadowings.py:171`
 * `f.model_dump(mode="json")`），但 `LibraryItemList.tsx` 非角色分支只渲染 title。
 *
 * 【修复契约（GREEN，方案 A：零后端改动）】
 * - 新增 prop `withForeshadowExtras?: boolean`（foreshadow 分类才渲染扩展，缺省 false）。
 * - 行内新增（挂在标题的 flex-1 truncate 之后，标题仍 flex-1 → 不被挤掉）：
 *   - 状态徽标  testid=`lib-fs-status-<id>`，文案 t('lib.fs.status.open'|'resolved')；
 *     resolved 命中时附加「已回收时间」（testid=`lib-fs-resolved-at-<id>`，仅 resolved_at 非空时渲染）
 *   - 优先级    testid=`lib-fs-priority-<id>`，文案 = t('lib.fs.priority') 渲染为「优先级 {n}」
 *   - 位置徽标  testid=`lib-fs-location-<id>`，原文照显 item.location（不做结构化解析，空串不渲染）
 * - 既有 lib-edit-<id>/lib-delete-<id> 与标题 flex-1 truncate 形态保持。
 * - withForeshadowExtras=false（其他分类）→ 不渲染任何 lib-fs-* 节点（不污染角色/世界观/大纲/时间线）。
 *
 * 【「第几章」口径】location 为自由文本（历史 94 条格式不一：
 * '第1-3章 梦境与觉醒' / '开篇梦境及醒来' / '第十一节·灶膛灰底'）→ 本契约只断言
 * 「原文照显」，**不**断言结构化章号（结构化列另开 issue 挂 0.16.0）。
 *
 * RED 预期：GREEN 前无 withForeshadowExtras prop / 无 lib-fs-* 节点 → element-missing，FAIL。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { LibraryItemList } from './LibraryItemList';
import type { LibraryItemDTO } from './LibraryCreateDialog';
import { useThemeStore } from '../stores/theme';
import { fetchAllChapters } from '../api/chapters';

/** #1350：组件缺省按 projectId 内部拉取章节序（同 #679 角色分组模式）→ 模块级 mock。 */
vi.mock('../api/chapters', () => ({
  fetchAllChapters: vi.fn(async () => ({ items: [], total: 0 })),
}));

/** 伏笔行种子（API 响应形状：title/priority/status/location/resolved_at） */
type FsItem = LibraryItemDTO & {
  status?: string;
  resolved_at?: string | null;
};

const FS_ITEMS: FsItem[] = [
  // open：无 resolved_at
  { id: 'f1', title: '师父闭关的真相', priority: 90, status: 'open', location: '第 11 章 · 闭关', resolved_at: null },
  // resolved：带回收时间
  {
    id: 'f2',
    title: '林晚照的旧玉佩',
    priority: 40,
    status: 'resolved',
    location: '第 8 章 · 初见',
    resolved_at: '2026-08-30T10:00:00Z',
  },
];

function renderFs(props?: Partial<Parameters<typeof LibraryItemList>[0]>) {
  return render(
    <LibraryItemList
      items={FS_ITEMS}
      withForeshadowExtras
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      {...props}
    />,
  );
}

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1324 伏笔行状态/优先级/位置渲染（对齐 design/GUI/foreshadow/foreshadow.html）', () => {
  it('N5：open 行渲染「未回收」状态徽标 + 「优先级 N」+ 位置文本', () => {
    renderFs();

    // 1. 状态徽标（open → 未回收）
    const status = screen.getByTestId('lib-fs-status-f1');
    expect(status).toBeInTheDocument();
    expect(status).toHaveTextContent('未回收');

    // 2. 优先级（N = item.priority）
    const pri = screen.getByTestId('lib-fs-priority-f1');
    expect(pri).toHaveTextContent('优先级 90');

    // 3. 位置（原文照显，不做结构化解析）
    expect(screen.getByTestId('lib-fs-location-f1')).toHaveTextContent('第 11 章 · 闭关');

    // 4. 标题仍在（未被挤掉）
    expect(screen.getByText('师父闭关的真相')).toBeInTheDocument();
  });

  it('已回收态：status=resolved → 「已回收」+ 回收时间', () => {
    renderFs();

    const status = screen.getByTestId('lib-fs-status-f2');
    expect(status).toHaveTextContent('已回收');
    // 回收时间（resolved_at 非空 → 渲染；本地时区渲染，断言只锚定 testid 存在 + 含年份）
    expect(screen.getByTestId('lib-fs-resolved-at-f2')).toHaveTextContent('2026');
    // 位置同样照显
    expect(screen.getByTestId('lib-fs-location-f2')).toHaveTextContent('第 8 章 · 初见');
  });

  it('反向断言：status=open（resolved_at 为 null）→ 不渲染「已回收」也不渲染回收时间', () => {
    renderFs();

    expect(screen.getByTestId('lib-fs-status-f1')).not.toHaveTextContent('已回收');
    expect(screen.getByTestId('lib-fs-status-f1')).toHaveTextContent('未回收');
    expect(screen.queryByTestId('lib-fs-resolved-at-f1')).not.toBeInTheDocument();
  });

  it('保留既有：悬停编辑/删除入口与标题 flex-1 truncate 形态不变', () => {
    renderFs();

    expect(screen.getByTestId('lib-edit-f1')).toBeInTheDocument();
    expect(screen.getByTestId('lib-delete-f1')).toBeInTheDocument();
    // 标题仍 flex-1 truncate（布局不被新字段挤掉）
    const title = screen.getByText('师父闭关的真相');
    expect(title).toHaveClass('flex-1');
    expect(title).toHaveClass('truncate');
  });

  it('位置文本为空 → 不渲染位置徽标（不出现空徽标）', () => {
    render(
      <LibraryItemList
        items={[{ id: 'f9', title: '无位置伏笔', priority: 50, status: 'open', location: '' } as FsItem]}
        withForeshadowExtras
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('lib-fs-location-f9')).not.toBeInTheDocument();
    // 其余字段不受影响
    expect(screen.getByTestId('lib-fs-status-f9')).toHaveTextContent('未回收');
    expect(screen.getByTestId('lib-fs-priority-f9')).toHaveTextContent('优先级 50');
  });

  it('可证伪自证：withForeshadowExtras=false（其他分类）→ 全无 lib-fs-* 节点', () => {
    renderFs({ withForeshadowExtras: false });

    // 状态徽标是本扩展的判据节点 —— 关闭扩展必须消失（防「无条件渲染」假绿）
    expect(screen.queryByTestId('lib-fs-status-f1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lib-fs-status-f2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lib-fs-priority-f1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lib-fs-location-f1')).not.toBeInTheDocument();
    // 既有行仍渲染
    expect(screen.getByText('师父闭关的真相')).toBeInTheDocument();
    expect(screen.getByTestId('lib-edit-f1')).toBeInTheDocument();
  });
});

// ══════════════════════════════════════════════════════════════════════════
// #1350：伏笔位置徽标「第 N 章 · location」（结构化章号 first_chapter_id 优先）
//
// 契约（GREEN）：
// - item.first_chapter_id 非空且能在章节序（chapterOrder）中定位 → 徽标文案
//   「第 N 章 · <location>」（N = 序位 + 1）；location 为空时只显示「第 N 章」。
// - first_chapter_id 为空，或不在章节序中（映射缺失）→ 回落既有 location 原文。
// - chapterOrder 未注入时按 projectId 内部拉取（同 #679 角色分组取数模式）。
// - location 仍为自由描述（#1324 契约不变，仅在其上叠加结构化章号前缀）。
// ══════════════════════════════════════════════════════════════════════════

/** 伏笔行种子（含 #1350 新增字段 first_chapter_id） */
type FsChapterItem = LibraryItemDTO & {
  status?: string;
  resolved_at?: string | null;
  first_chapter_id?: string | null;
};

const CHAPTER_ORDER = ['c1', 'c2', 'c3'];

const FS_CHAPTER_ITEMS: FsChapterItem[] = [
  // 章号命中 + 有 location → 「第 3 章 · 闭关」
  { id: 'g1', title: '铜镜的秘密', priority: 90, status: 'open', location: '闭关', first_chapter_id: 'c3' },
  // 无章号（存量形态）→ 回落 location
  { id: 'g2', title: '玉佩的裂痕', priority: 50, status: 'open', location: '初见', first_chapter_id: null },
  // 章号命中但 location 为空 → 只显示「第 2 章」
  { id: 'g3', title: '无位置伏笔', priority: 50, status: 'open', location: '', first_chapter_id: 'c2' },
  // 章号不在章节序中（映射缺失）→ 回落 location，不伪造章号
  { id: 'g4', title: '未知章节伏笔', priority: 50, status: 'open', location: '山门', first_chapter_id: 'cX' },
];

function renderFsChapter(props?: Partial<Parameters<typeof LibraryItemList>[0]>) {
  return render(
    <LibraryItemList
      items={FS_CHAPTER_ITEMS}
      withForeshadowExtras
      chapterOrder={CHAPTER_ORDER}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      {...props}
    />,
  );
}

describe('#1350 伏笔位置徽标「第 N 章 · location」（结构化章号优先，空值回落）', () => {
  beforeEach(() => {
    useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
    vi.mocked(fetchAllChapters).mockClear();
  });

  it('N2：first_chapter_id 命中章节序 → 「第 N 章 · location」（N = 序位 + 1）', () => {
    renderFsChapter();

    expect(screen.getByTestId('lib-fs-location-g1')).toHaveTextContent('第 3 章 · 闭关');
  });

  it('N2：first_chapter_id 为空 → 回落纯 location 文本（存量形态不变）', () => {
    renderFsChapter();

    const badge = screen.getByTestId('lib-fs-location-g2');
    expect(badge).toHaveTextContent('初见');
    expect(badge).not.toHaveTextContent('第');
  });

  it('location 为空但章号命中 → 只显示「第 N 章」（不出现孤悬分隔符）', () => {
    renderFsChapter();

    const badge = screen.getByTestId('lib-fs-location-g3');
    expect(badge).toHaveTextContent('第 2 章');
    expect(badge).not.toHaveTextContent('·');
  });

  it('章号不在章节序中（映射缺失）→ 回落 location，不伪造章号', () => {
    renderFsChapter();

    const badge = screen.getByTestId('lib-fs-location-g4');
    expect(badge).toHaveTextContent('山门');
    expect(badge).not.toHaveTextContent('第');
  });

  it('未注入 chapterOrder → 按 projectId 内部拉取章节序（同 #679 模式）', async () => {
    vi.mocked(fetchAllChapters).mockResolvedValueOnce({
      items: [
        { id: 'c1', title: '觉醒', volume_id: null, order_index: 0, word_count: 0 },
        { id: 'c2', title: '拜师', volume_id: null, order_index: 1, word_count: 0 },
        { id: 'c3', title: '结丹', volume_id: null, order_index: 2, word_count: 0 },
      ],
      total: 3,
    });

    render(
      <LibraryItemList
        items={[FS_CHAPTER_ITEMS[0]]}
        withForeshadowExtras
        projectId="p1"
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId('lib-fs-location-g1')).toHaveTextContent('第 3 章 · 闭关'),
    );
    expect(fetchAllChapters).toHaveBeenCalledWith('p1');
  });
});
