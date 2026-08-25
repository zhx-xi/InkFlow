/**
 * ExportDialog 契约测试（项目导出对话框 RED 阶段）
 *
 * ⚠️ 本文件 = 契约。GREEN 必须新建 src/components/ExportDialog.tsx 并匹配：
 *
 * export function ExportDialog({ project: Project, onClose: () => void }): JSX.Element
 * （Project 类型来自 ../stores/project：id/name/tags/language/target_words/config/created_at/updated_at）
 *
 * 结构 testid：
 * - project-export-dialog（对话框容器）
 * - export-include-settings（设定档案附录 checkbox，默认 checked=true；label「设定档案附录」）
 * - export-location-input（导出位置输入框：mount 时写入 getDefaultLocation() 结果）
 * - export-filename-input（文件名输入框：默认 `${project.name}.txt`）
 * - export-browse（浏览按钮 → chooseDirectory() 结果写入 location input）
 * - export-submit（导出按钮：下载中 disabled + 出现 export-loading 加载指示）
 * - export-cancel（取消按钮 → onClose()）
 * - 「正文」行（必含，label 文本 = t('export.body')）
 *
 * window.INKFLOW_API.file（GREEN 补 ApiConfig.file，preload file 命名空间）：
 * - getDefaultLocation(): Promise<string>       // mount 时调用一次
 * - chooseDirectory(): Promise<string>          // 点浏览时调用
 * - saveExport({ path, filename, content }): Promise<{ path, filename }>  // 提交时调用
 *
 * 导出流程：
 * - 点 export-submit → GET {baseURL}/api/v1/projects/{id}/export?format=txt&include_settings=true
 *   （include_settings=false 时 URL 省略该参数，见 src/api/export.test.ts 契约）
 * - 响应 text/plain（非 JSON）→ res.text() 取 content
 * - saveExport.filename = 文件名输入框当前值（测试未编辑输入框 → 默认 剑来.txt；
 *   Content-Disposition 文件名由 api 层解析（exportProjectFile），不覆盖输入框语义）
 * - saveExport 成功 → onClose() + ok toast「导出成功」
 * - saveExport 抛错 → err toast（message = errorMessage(err)），onClose 不调用
 *
 * 测试策略：不 mock ../api/client，直接 stub 全局 fetch（URL 可精确断言；GREEN 无论
 * 直连 fetch 或经 src/api/export.ts exportProjectFile 均命中同一 URL）；toast 断言
 * useToastStore 状态（ProviderDialog.test 同款模式）。
 *
 * 新增 i18n key（GREEN 补 zh.ts/en.ts；toast 文案本测试直写中文锁定）：
 * export.title='导出项目' export.body='正文' export.includeSettings='设定档案附录'
 * export.location='导出位置' export.filename='文件名' export.browse='浏览'
 * export.submit='导出' export.cancel='取消' export.loading='导出中…'
 * export.ok='导出成功'
 *
 * RED 预期：./ExportDialog 模块不存在 → 收集期 Failed to resolve import（Failed Suites 1，
 * 非逐用例失败）。这是有效 RED，GREEN 实现前不得修改本文件。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExportDialog } from './ExportDialog';
import type { Project } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';
import type { ApiConfig } from '../api/client';

const BASE = 'http://local';

/** 契约结构镜像：ApiConfig.file 由 GREEN 补全（此处 cast 明确标注） */
interface FileApiMock {
  getDefaultLocation: ReturnType<typeof vi.fn>;
  chooseDirectory: ReturnType<typeof vi.fn>;
  saveExport: ReturnType<typeof vi.fn>;
}

const project: Project = {
  id: 'p1',
  name: '剑来',
  tags: [],
  language: 'zh',
  target_words: 800000,
  config: {},
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

let fileApi: FileApiMock;
let fetchMock: ReturnType<typeof vi.fn>;

/** text/plain 导出响应（非 JSON；Content-Disposition 供 api 层解析文件名，组件不锁定其回填） */
function exportResponse(): Response {
  return new Response('正文文本', {
    status: 200,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Content-Disposition': "attachment; filename*=UTF-8''%E5%89%91%E6%9D%A5-txt.txt",
    },
  });
}

/** 可控未决 Promise（下载中态断言用） */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function renderDialog(overrides?: { onClose?: () => void }) {
  const onClose = overrides?.onClose ?? vi.fn();
  render(<ExportDialog project={project} onClose={onClose} />);
  return { onClose };
}

beforeEach(() => {
  vi.unstubAllGlobals();
  fileApi = {
    getDefaultLocation: vi.fn(),
    chooseDirectory: vi.fn(),
    saveExport: vi.fn(),
  };
  window.INKFLOW_API = {
    baseURL: BASE,
    token: 'tok',
    file: fileApi,
  } as unknown as ApiConfig;
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useToastStore.setState({ toasts: [] });
  // 默认：mount 即得导出位置（各用例可覆盖）
  fileApi.getDefaultLocation.mockResolvedValue('C:\\Users\\test\\Desktop');
  fetchMock = vi.fn();
  fetchMock.mockResolvedValue(exportResponse());
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  delete window.INKFLOW_API;
  vi.unstubAllGlobals();
});

describe('ExportDialog — 渲染与默认值', () => {
  it('渲染对话框容器 project-export-dialog，含「正文」行与默认勾选的设定档案附录 checkbox', () => {
    renderDialog();
    const dlg = screen.getByTestId('project-export-dialog');
    expect(within(dlg).getByText('正文')).toBeInTheDocument();
    expect(within(dlg).getByText('设定档案附录')).toBeInTheDocument();
    expect(screen.getByTestId('export-include-settings')).toBeChecked();
  });

  it('mount → getDefaultLocation() 返回值写入导出位置输入框（含 Desktop）', async () => {
    renderDialog();
    await waitFor(() => expect(fileApi.getDefaultLocation).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      const input = screen.getByTestId('export-location-input') as HTMLInputElement;
      expect(input.value).toContain('Desktop');
    });
  });

  it('文件名输入框默认值 = `${project.name}.txt`（剑来 → 剑来.txt）', () => {
    renderDialog();
    const input = screen.getByTestId('export-filename-input') as HTMLInputElement;
    expect(input.value).toBe('剑来.txt');
  });
});

describe('ExportDialog — 浏览目录', () => {
  it('点 export-browse → chooseDirectory() → 返回值写入导出位置输入框', async () => {
    fileApi.chooseDirectory.mockResolvedValue('D:\\out');
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByTestId('export-browse'));
    await waitFor(() => expect(fileApi.chooseDirectory).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      const input = screen.getByTestId('export-location-input') as HTMLInputElement;
      expect(input.value).toBe('D:\\out');
    });
  });
});

describe('ExportDialog — 提交导出', () => {
  it('点 export-submit → fetch GET /projects/p1/export?format=txt&include_settings=true → saveExport({path, filename, content}) → onClose + ok toast「导出成功」', async () => {
    fileApi.saveExport.mockResolvedValue({ path: 'C:\\Users\\test\\Desktop', filename: '剑来.txt' });
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    // 等 mount 异步（getDefaultLocation）落定，锁定 location 值
    await waitFor(() => {
      const input = screen.getByTestId('export-location-input') as HTMLInputElement;
      expect(input.value).toContain('Desktop');
    });
    await user.click(screen.getByTestId('export-submit'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock.mock.calls[0][0]).toBe(
        `${BASE}/api/v1/projects/p1/export?format=txt&include_settings=true`,
      );
    });
    await waitFor(() => {
      expect(fileApi.saveExport).toHaveBeenCalledWith({
        path: 'C:\\Users\\test\\Desktop',
        filename: '剑来.txt',
        content: '正文文本',
      });
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.length).toBeGreaterThan(0);
      const last = toasts[toasts.length - 1];
      expect(last.type).toBe('ok');
      expect(last.message).toBe('导出成功');
    });
  });

  it('saveExport 抛错 → err toast（errorMessage(err)）+ onClose 不调用', async () => {
    fileApi.saveExport.mockRejectedValue(new Error('磁盘写入失败'));
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    await user.click(screen.getByTestId('export-submit'));

    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.length).toBeGreaterThan(0);
      const last = toasts[toasts.length - 1];
      expect(last.type).toBe('err');
      expect(last.message).toBe('磁盘写入失败');
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('下载中：export-submit disabled + export-loading 出现（saveExport 未决期间）', async () => {
    const d = deferred<{ path: string; filename: string }>();
    fileApi.saveExport.mockReturnValue(d.promise);
    const user = userEvent.setup();
    renderDialog();
    await waitFor(() => {
      const input = screen.getByTestId('export-location-input') as HTMLInputElement;
      expect(input.value).toContain('Desktop');
    });
    await user.click(screen.getByTestId('export-submit'));
    await waitFor(() => expect(fileApi.saveExport).toHaveBeenCalled());
    expect(screen.getByTestId('export-submit')).toBeDisabled();
    expect(screen.getByTestId('export-loading')).toBeInTheDocument();
    // 收尾：resolve 未决 Promise，避免悬挂
    d.resolve({ path: 'C:\\Users\\test\\Desktop', filename: '剑来.txt' });
  });
});

describe('ExportDialog — 取消', () => {
  it('点 export-cancel → onClose()', async () => {
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    await user.click(screen.getByTestId('export-cancel'));
    expect(onClose).toHaveBeenCalled();
  });
});
