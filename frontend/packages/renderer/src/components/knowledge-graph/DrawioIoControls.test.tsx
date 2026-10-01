/**
 * #1360 drawio 导入/导出前端契约（RED 先行；父侧作者）
 *
 * ═══════════════════════════════════════════════════════════════════════
 * 【要证明的命题】
 * 知识图谱视图工具栏提供「导出 drawio / 导入 drawio」两个动作：
 * - 导出：拉 mxGraph XML → 经 Electron file IPC 写盘（默认目录 + 服务端文件名）
 * - 导入：弹层选文件 + 选 merge|replace（replace 需勾选确认）→ 回报 imported/skipped/failed
 * ═══════════════════════════════════════════════════════════════════════
 *
 * 【契约（父侧定稿，2026-10-02，spec §5.7 / specs/f19-gui/knowledge.md）】
 *
 * 1. api/knowledge-graph.ts 新增（**非 JSON 传输**，镜像 api/export.ts 的原始 fetch 形态）：
 *    - exportKnowledgeGraphFile(projectId) -> { filename, content }
 *      GET /api/v1/projects/{pid}/knowledge-graph/export?format=mxgraph
 *    - importKnowledgeGraphFile(projectId, xml, mode) -> KnowledgeGraphImportResult
 *      POST /api/v1/projects/{pid}/knowledge-graph/import?mode=<mode>（Content-Type application/xml）
 *    - 类型：KnowledgeGraphImportMode = 'merge' | 'replace'
 *            KnowledgeGraphImportIssue { kind, edge_id, label, reason }
 *            KnowledgeGraphImportResult { mode, total, imported, skipped, failed, deleted, details }
 *
 * 2. 工具栏（`<DrawioIoControls projectId onImported />`，挂在 KnowledgeGraphView 工具栏行内）：
 *    - `library-kg-export-drawio` → exportKnowledgeGraphFile(projectId)
 *      → window.INKFLOW_API.file.getDefaultLocation() → saveExport({ path, filename, content })
 *      → 状态行 `library-kg-drawio-status` 显示保存路径；失败 → `library-kg-drawio-error`
 *    - `library-kg-import-drawio` → 打开弹层 `library-kg-import-dialog`
 *
 * 3. 导入弹层（遮罩卡片，同 RelationForm 形态）：
 *    - 文件选择 `library-kg-import-file`（input type=file，accept .drawio/.xml）
 *    - 模式单选 `library-kg-import-mode-merge` / `library-kg-import-mode-replace`（默认 merge）
 *    - 选 replace → 出现确认勾选框 `library-kg-import-replace-ack`（危险提示：将清空既有关系）
 *    - 提交 `library-kg-import-submit`：**未选文件 / replace 未勾选确认 → disabled**
 *    - 取消 `library-kg-import-cancel` → 关闭弹层，不调 API
 *    - 成功 → 结果区 `library-kg-import-result`（含 imported / skipped / failed 计数）
 *      + 调 onImported()（父侧 bump reloadKey 触发图谱重拉）
 *    - 失败 → `library-kg-import-error`（errorMessage(err)），弹层保持打开
 *
 * 【RED 预期】DrawioIoControls.tsx 不存在 → 收集期加载失败（实现后即愈）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DrawioIoControls } from './DrawioIoControls';
import { KnowledgeGraphView } from './KnowledgeGraphView';
import { knowledgeDrawioZh } from '../../i18n/knowledge-drawio';
import { useThemeStore } from '../../stores/theme';
import {
  exportKnowledgeGraphFile,
  importKnowledgeGraphFile,
} from '../../api/knowledge-graph';

vi.mock('../../api/knowledge-graph', () => ({
  exportKnowledgeGraphFile: vi.fn(),
  importKnowledgeGraphFile: vi.fn(),
}));

const exportMock = vi.mocked(exportKnowledgeGraphFile);
const importMock = vi.mocked(importKnowledgeGraphFile);

const PROJECT_ID = 'p1';

const XML = '<mxfile><diagram><mxGraphModel><root /></mxGraphModel></diagram></mxfile>';

function makeFileApi() {
  return {
    getDefaultLocation: vi.fn().mockResolvedValue('C:\\Users\\test\\Desktop'),
    chooseDirectory: vi.fn(),
    saveExport: vi.fn().mockResolvedValue({ path: 'C:\\Users\\test\\Desktop', filename: 'a.drawio' }),
  };
}

let fileApi: ReturnType<typeof makeFileApi>;

beforeEach(() => {
  vi.clearAllMocks();
  // 结果文案断言锁定 zh 模板（避免依赖运行环境默认语言）
  useThemeStore.setState({ lang: 'zh' });
  fileApi = makeFileApi();
  window.INKFLOW_API = {
    baseURL: 'http://127.0.0.1:8000',
    token: 't',
    file: fileApi,
  } as unknown as typeof window.INKFLOW_API;
  exportMock.mockResolvedValue({ filename: '青云志-knowledge-graph.drawio', content: XML });
  importMock.mockResolvedValue({
    mode: 'merge',
    total: 3,
    imported: 1,
    skipped: 1,
    failed: 1,
    deleted: 0,
    details: [
      { kind: 'skipped', edge_id: 'kr:1', label: '师承', reason: '该关系已存在（同键唯一）' },
      { kind: 'failed', edge_id: 'kr:2', label: '自指', reason: '关系两端不能是同一实体（自环）' },
    ],
  });
});

function renderControls(onImported = vi.fn()) {
  render(<DrawioIoControls projectId={PROJECT_ID} onImported={onImported} />);
  return onImported;
}

describe('#1360 drawio 工具栏', () => {
  it('渲染「导出 drawio」「导入 drawio」两个按钮', () => {
    renderControls();
    expect(screen.getByTestId('library-kg-export-drawio')).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-import-drawio')).toBeInTheDocument();
  });

  it('点导出 → 拉 XML → 经 file IPC 写盘（默认目录 + 服务端文件名）', async () => {
    const user = userEvent.setup();
    renderControls();

    await user.click(screen.getByTestId('library-kg-export-drawio'));

    await waitFor(() => expect(exportMock).toHaveBeenCalledWith(PROJECT_ID));
    await waitFor(() =>
      expect(fileApi.saveExport).toHaveBeenCalledWith({
        path: 'C:\\Users\\test\\Desktop',
        filename: '青云志-knowledge-graph.drawio',
        content: XML,
      }),
    );
    expect(await screen.findByTestId('library-kg-drawio-status')).toBeInTheDocument();
  });

  it('导出失败 → 错误提示（不静默）', async () => {
    const user = userEvent.setup();
    exportMock.mockRejectedValue(new Error('内核未就绪'));
    renderControls();

    await user.click(screen.getByTestId('library-kg-export-drawio'));

    const err = await screen.findByTestId('library-kg-drawio-error');
    expect(err).toHaveTextContent('内核未就绪');
  });

  it('无 file IPC（浏览器 dev）→ 报错而非假成功', async () => {
    const user = userEvent.setup();
    // 浏览器 dev 无 preload 注入：file 命名空间缺失 → 无法写盘
    window.INKFLOW_API = {
      baseURL: 'http://127.0.0.1:8000',
      token: 't',
    } as unknown as typeof window.INKFLOW_API;
    renderControls();

    await user.click(screen.getByTestId('library-kg-export-drawio'));

    expect(await screen.findByTestId('library-kg-drawio-error')).toBeInTheDocument();
    expect(screen.queryByTestId('library-kg-drawio-status')).toBeNull();
  });
});

describe('#1360 drawio 导入弹层', () => {
  it('点导入 → 打开弹层，默认 merge 模式', async () => {
    const user = userEvent.setup();
    renderControls();

    await user.click(screen.getByTestId('library-kg-import-drawio'));

    const dialog = await screen.findByTestId('library-kg-import-dialog');
    expect(within(dialog).getByTestId('library-kg-import-mode-merge')).toBeChecked();
    expect(within(dialog).getByTestId('library-kg-import-mode-replace')).not.toBeChecked();
  });

  it('未选文件 → 提交按钮 disabled', async () => {
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByTestId('library-kg-import-drawio'));
    await screen.findByTestId('library-kg-import-dialog');

    expect(screen.getByTestId('library-kg-import-submit')).toBeDisabled();
  });

  it('选 replace → 出现确认勾选框；未勾选时提交 disabled', async () => {
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByTestId('library-kg-import-drawio'));
    await screen.findByTestId('library-kg-import-dialog');

    await user.click(screen.getByTestId('library-kg-import-mode-replace'));
    const ack = await screen.findByTestId('library-kg-import-replace-ack');
    expect(ack).not.toBeChecked();

    await user.upload(
      screen.getByTestId('library-kg-import-file'),
      new File([XML], 'g.drawio', { type: 'application/xml' }),
    );
    expect(screen.getByTestId('library-kg-import-submit')).toBeDisabled();

    await user.click(ack);
    expect(screen.getByTestId('library-kg-import-submit')).toBeEnabled();
  });

  it('选文件 + merge 提交 → 调 API(pid, xml, merge) + 回报计数 + onImported', async () => {
    const user = userEvent.setup();
    const onImported = renderControls();
    await user.click(screen.getByTestId('library-kg-import-drawio'));
    await screen.findByTestId('library-kg-import-dialog');

    await user.upload(
      screen.getByTestId('library-kg-import-file'),
      new File([XML], 'g.drawio', { type: 'application/xml' }),
    );
    await user.click(screen.getByTestId('library-kg-import-submit'));

    await waitFor(() => expect(importMock).toHaveBeenCalledWith(PROJECT_ID, XML, 'merge'));
    const result = await screen.findByTestId('library-kg-import-result');
    // 断言渲染文本 = zh 结果模板逐字插值：计数敏感（值错即红）+ 不锁死措辞（文案可自由演化）
    expect(result).toHaveTextContent(
      knowledgeDrawioZh['lib.knowledge.drawio.result']
        .replace('{imported}', '1')
        .replace('{skipped}', '1')
        .replace('{failed}', '1'),
    );
    await waitFor(() => expect(onImported).toHaveBeenCalledTimes(1));
  });

  it('replace 勾选确认后提交 → 调 API(pid, xml, replace)', async () => {
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByTestId('library-kg-import-drawio'));
    await screen.findByTestId('library-kg-import-dialog');

    await user.click(screen.getByTestId('library-kg-import-mode-replace'));
    await user.upload(
      screen.getByTestId('library-kg-import-file'),
      new File([XML], 'g.drawio', { type: 'application/xml' }),
    );
    await user.click(screen.getByTestId('library-kg-import-replace-ack'));
    await user.click(screen.getByTestId('library-kg-import-submit'));

    await waitFor(() => expect(importMock).toHaveBeenCalledWith(PROJECT_ID, XML, 'replace'));
  });

  it('取消 → 关闭弹层且不调 API', async () => {
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByTestId('library-kg-import-drawio'));
    await screen.findByTestId('library-kg-import-dialog');

    await user.click(screen.getByTestId('library-kg-import-cancel'));

    await waitFor(() => expect(screen.queryByTestId('library-kg-import-dialog')).toBeNull());
    expect(importMock).not.toHaveBeenCalled();
  });

  it('导入失败 → 错误提示且弹层保持打开', async () => {
    const user = userEvent.setup();
    importMock.mockRejectedValue(new Error('非法 mxGraph XML：根元素不是 mxfile'));
    renderControls();
    await user.click(screen.getByTestId('library-kg-import-drawio'));
    await screen.findByTestId('library-kg-import-dialog');

    await user.upload(
      screen.getByTestId('library-kg-import-file'),
      new File(['<broken>'], 'bad.drawio', { type: 'application/xml' }),
    );
    await user.click(screen.getByTestId('library-kg-import-submit'));

    const err = await screen.findByTestId('library-kg-import-error');
    expect(err).toHaveTextContent('非法 mxGraph XML');
    expect(screen.getByTestId('library-kg-import-dialog')).toBeInTheDocument();
  });
});

describe('#1360 图谱视图工具栏接线', () => {
  it('KnowledgeGraphView 工具栏渲染 drawio 导入/导出控件（projectId 透传）', () => {
    render(
      <KnowledgeGraphView
        nodes={[]}
        edges={[]}
        relations={[]}
        view="list"
        onViewChange={vi.fn()}
        onCreateRelation={vi.fn()}
        onEditRelation={vi.fn()}
        onDeleteRelation={vi.fn()}
        onOpenEntity={vi.fn()}
        onEditEdge={vi.fn()}
        onDeleteEdge={vi.fn()}
        onGoEntities={vi.fn()}
        projectId={PROJECT_ID}
        onImported={vi.fn()}
      />,
    );

    expect(screen.getByTestId('library-kg-export-drawio')).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-import-drawio')).toBeInTheDocument();
  });
});
