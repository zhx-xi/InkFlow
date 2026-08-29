/**
 * #480 检索页（RAG embedding 增强检索）RED 阶段契约测试
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/pages/search.tsx（命名导出 SearchPage），必须匹配：
 *
 * 接线（Mock 依赖）：
 * - SearchPage 必须 import { fetchSearch } from '../api/search'（本文件 vi.mock 该模块；
 *   GREEN 若改 import 源 → mock 不生效 → 测试炸，属契约违约）
 * - 项目上下文来自 useProjectStore（projects / currentProjectId，测试经 setState 播种）
 * - 检索参数 = fetchSearch({ q, projectId, mode })；mode 默认 'semantic'（本轨默认语义检索）
 * - 初始不自动检索：挂载不发请求，点搜索按钮才发起；q strip 后为空 → 不发
 *
 * data-testid 即契约：
 * - search-page 根容器
 * - search-input 检索输入（role=textbox，aria-label 含「检索」= t('search.placeholder')）
 * - search-mode-select 模式切换（既有 Radix Select：SelectTrigger 落点 + portal 选项
 *   role=option；默认「语义」，可切「关键词」）——同 library-project-select 模式
 * - search-project-select 项目选择（选项来自 useProjectStore.projects）
 * - search-btn 搜索按钮（文案 t('search.btn')='检索'）
 * - search-results 结果区；search-hit 单条命中（含 title / snippet / entity_type 徽标 / score）
 * - search-empty 空态（total=0）；search-loading 加载态；search-error 错误态（文案含失败信息）
 * - search-no-project 无项目态（projects 为空，引导去项目页；不发检索）
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：
 * search.title='检索' search.sub='基于 RAG embedding 的语义/关键词检索'
 * search.placeholder='输入要检索的内容…' search.mode.label='检索模式'
 * search.mode.keyword='关键词' search.mode.semantic='语义' search.project.label='项目'
 * search.project.placeholder='选择项目' search.btn='检索' search.empty='未找到相关内容'
 * search.noProject='请先创建或选择项目' search.loading='检索中…' search.error='检索失败，请重试'
 * search.results='共 {total} 条结果'
 *
 * RED 预期：./search 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { SearchPage } from './search';
import { fetchSearch } from '../api/search';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore, type Project } from '../stores/project';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/search', () => ({ fetchSearch: vi.fn() }));

const fetchSearchMock = vi.mocked(fetchSearch);

/** 契约结构镜像（GREEN 类型从 api/search.ts 导出；本文件内联镜像供 mock 播种） */
interface SearchHitDto {
  entity_type: string;
  entity_id: string;
  project_id: string;
  title: string;
  snippet: string;
  score: number;
}

interface SearchResponseDto {
  total: number;
  hits: SearchHitDto[];
  query: string;
  types: string[] | null;
  mode: 'keyword' | 'semantic';
  project_ids: string[];
}

const searchResponseDto: SearchResponseDto = {
  total: 2,
  hits: [
    { entity_type: 'character', entity_id: 'e1', project_id: 'p1', title: '林惊羽', snippet: '青云门弟子…', score: 0.87 },
    { entity_type: 'chapter', entity_id: 'e2', project_id: 'p1', title: '第一章 青云山', snippet: '青云山脚下…', score: 0.72 },
  ],
  query: '青云',
  types: null,
  mode: 'semantic',
  project_ids: ['p1'],
};

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: '青云志',
    tags: ['玄幻'],
    language: 'zh-CN',
    target_words: 800000,
    config: {},
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
    ...overrides,
  };
}

/** 播种项目列表 + 当前项目（缺省 p1 已选中，免手动选择；传 null 模拟未选择） */
function seedProjects(currentProjectId: string | null = 'p1') {
  useProjectStore.setState({
    projects: [makeProject(), makeProject({ id: 'p2', name: '山海经' })],
    currentProjectId,
    loading: false,
    error: null,
  });
}

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location-display">{location.pathname}{location.search}</div>;
}

function renderSearchPage() {
  return render(
    <MemoryRouter>
      <SearchPage />
      <LocationDisplay />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  fetchSearchMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('检索页 — 无项目态', () => {
  it('projects 为空 → search-no-project 引导空态（不发检索）', () => {
    renderSearchPage();
    expect(screen.getByTestId('search-no-project')).toBeInTheDocument();
    expect(screen.queryByTestId('search-input')).not.toBeInTheDocument();
    expect(fetchSearchMock).not.toHaveBeenCalled();
  });
});

describe('检索页 — 表单渲染', () => {
  it('有项目 → 输入框/模式/项目选择/搜索按钮齐全，初始无结果区/空态', () => {
    seedProjects();
    renderSearchPage();

    expect(screen.getByTestId('search-page')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /检索/ })).toBeInTheDocument();
    expect(screen.getByTestId('search-mode-select')).toBeInTheDocument();
    expect(screen.getByTestId('search-project-select')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '检索' })).toBeInTheDocument();

    // 初始无检索结果：无命中、无空态、无加载、无错误
    expect(screen.queryByTestId('search-hit')).not.toBeInTheDocument();
    expect(screen.queryByTestId('search-empty')).not.toBeInTheDocument();
    expect(screen.queryByTestId('search-loading')).not.toBeInTheDocument();
    expect(screen.queryByTestId('search-error')).not.toBeInTheDocument();
    expect(fetchSearchMock).not.toHaveBeenCalled();
  });
});

describe('检索页 — 检索交互（#480）', () => {
  it('输入 q + 选择项目 + 点检索 → fetchSearch(q/projectId/mode=semantic) → 命中渲染', async () => {
    seedProjects(null);
    fetchSearchMock.mockResolvedValue(searchResponseDto);
    const user = userEvent.setup();
    renderSearchPage();

    await user.type(screen.getByRole('textbox', { name: /检索/ }), '青云');
    await user.click(screen.getByTestId('search-project-select'));
    await user.click(await screen.findByRole('option', { name: '青云志' }));
    await user.click(screen.getByRole('button', { name: '检索' }));

    await waitFor(() => {
      expect(fetchSearchMock).toHaveBeenCalledWith(
        expect.objectContaining({ q: '青云', projectId: 'p1', mode: 'semantic' }),
      );
    });
    expect(await screen.findByTestId('search-results')).toBeInTheDocument();
    const hits = await screen.findAllByTestId('search-hit');
    expect(hits).toHaveLength(2);
    const hit = hits[0];
    expect(within(hit).getByText('林惊羽')).toBeInTheDocument(); // title
    expect(within(hit).getByText('青云门弟子…')).toBeInTheDocument(); // snippet
    expect(hit).toHaveTextContent(/角色|character/i); // entity_type 徽标
    expect(hit).toHaveTextContent(/0\.87|87/); // score
  });

  it('模式切换：默认语义，切「关键词」后检索参数 mode=keyword', async () => {
    seedProjects();
    fetchSearchMock.mockResolvedValue(searchResponseDto);
    const user = userEvent.setup();
    renderSearchPage();

    const modeSelect = screen.getByTestId('search-mode-select');
    expect(modeSelect).toHaveTextContent('语义'); // 默认 semantic
    await user.click(modeSelect);
    await user.click(await screen.findByRole('option', { name: '关键词' }));
    expect(screen.getByTestId('search-mode-select')).toHaveTextContent('关键词');

    await user.type(screen.getByRole('textbox', { name: /检索/ }), '青云');
    await user.click(screen.getByRole('button', { name: '检索' }));
    await waitFor(() => {
      expect(fetchSearchMock).toHaveBeenCalledWith(
        expect.objectContaining({ q: '青云', projectId: 'p1', mode: 'keyword' }),
      );
    });
  });

  it('q 全空白（strip 后为空）→ 不发起检索', async () => {
    seedProjects();
    const user = userEvent.setup();
    renderSearchPage();

    await user.type(screen.getByRole('textbox', { name: /检索/ }), '   ');
    await user.click(screen.getByRole('button', { name: '检索' }));

    expect(fetchSearchMock).not.toHaveBeenCalled();
  });

  it('total=0 → search-empty 空态', async () => {
    seedProjects();
    fetchSearchMock.mockResolvedValue({ ...searchResponseDto, total: 0, hits: [] });
    const user = userEvent.setup();
    renderSearchPage();

    await user.type(screen.getByRole('textbox', { name: /检索/ }), '青云');
    await user.click(screen.getByRole('button', { name: '检索' }));

    expect(await screen.findByTestId('search-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('search-hit')).not.toBeInTheDocument();
  });

  it('fetchSearch reject → search-error 错误态（文案含失败信息）', async () => {
    seedProjects();
    fetchSearchMock.mockRejectedValue(new Error('内核未就绪'));
    const user = userEvent.setup();
    renderSearchPage();

    await user.type(screen.getByRole('textbox', { name: /检索/ }), '青云');
    await user.click(screen.getByRole('button', { name: '检索' }));

    const err = await screen.findByTestId('search-error');
    expect(err).toHaveTextContent(/检索失败|内核未就绪/);
  });

  it('检索中 → search-loading 出现；resolve 后渲染结果、加载态消失', async () => {
    seedProjects();
    let resolveSearch!: (v: SearchResponseDto) => void;
    fetchSearchMock.mockImplementation(
      () => new Promise<SearchResponseDto>((resolve) => { resolveSearch = resolve; }),
    );
    const user = userEvent.setup();
    renderSearchPage();

    await user.type(screen.getByRole('textbox', { name: /检索/ }), '青云');
    await user.click(screen.getByRole('button', { name: '检索' }));

    expect(await screen.findByTestId('search-loading')).toBeInTheDocument();
    resolveSearch(searchResponseDto);
    expect(await screen.findByTestId('search-results')).toBeInTheDocument();
    expect(screen.queryByTestId('search-loading')).not.toBeInTheDocument();
  });
});

describe('检索页 — 命中跳转（#683）', () => {
  const makeHit = (entity_type: string, entity_id: string, title: string): SearchHitDto => ({
    entity_type,
    entity_id,
    project_id: 'p1',
    title,
    snippet: `${title} 的相关片段…`,
    score: 0.5,
  });

  /** 播种项目 + mock 检索响应 + 渲染 + 输入/检索 → 返回出现首条命中 */
  async function searchHits(hits: SearchHitDto[]) {
    fetchSearchMock.mockResolvedValue({ ...searchResponseDto, hits });
    renderSearchPage();
    const user = userEvent.setup();
    await user.type(screen.getByRole('textbox', { name: /检索/ }), '青云');
    await user.click(screen.getByRole('button', { name: '检索' }));
    await screen.findByTestId('search-hit');
  }

  it('命中卡片可点击：带 cursor-pointer + hover 态 + aria-label', async () => {
    seedProjects();
    await searchHits([makeHit('character', 'e1', '林惊羽')]);
    const hit = screen.getByTestId('search-hit');
    expect(hit.className).toContain('cursor-pointer');
    expect(hit.className).toContain('hover:bg-');
    expect(hit).toHaveAttribute('aria-label');
    expect(hit.getAttribute('aria-label')?.trim().length ?? 0).toBeGreaterThan(0);
  });

  it('点击章节命中 → navigate(/writing) + useChapterStore.selectChapter(entity_id)', async () => {
    seedProjects();
    const selectChapterSpy = vi
      .spyOn(useChapterStore.getState(), 'selectChapter')
      .mockResolvedValue();
    await searchHits([makeHit('chapter', 'e2', '第一章 青云山')]);
    const user = userEvent.setup();
    await user.click(screen.getByTestId('search-hit'));
    expect(screen.getByTestId('location-display')).toHaveTextContent('/writing');
    expect(selectChapterSpy).toHaveBeenCalledWith('e2');
  });

  it.each([
    ['character', 'characters'],
    ['world', 'world'],
    ['outline', 'outline'],
    ['timeline', 'timeline'],
    ['foreshadow', 'foreshadow'],
  ])('点击 %s 命中 → navigate(/library?cat=%s)', async (entityType, cat) => {
    seedProjects();
    await searchHits([makeHit(entityType, `id-${entityType}`, `${entityType} 条目`)]);
    const user = userEvent.setup();
    await user.click(screen.getByTestId('search-hit'));
    expect(screen.getByTestId('location-display')).toHaveTextContent(`/library?cat=${cat}`);
  });
});

describe('检索页 — 未选项目不发请求（spec N2）', () => {
  it('有项目列表但 currentProjectId=null → 点检索不发请求', async () => {
    seedProjects(null); // projects 非空，但 currentProjectId=null（未选项目）
    const user = userEvent.setup();
    renderSearchPage();
    await user.type(screen.getByRole('textbox', { name: /检索/ }), '青云');
    await user.click(screen.getByRole('button', { name: '检索' }));
    expect(fetchSearchMock).not.toHaveBeenCalled();
  });
});
