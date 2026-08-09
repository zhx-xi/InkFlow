/**
 * F34 章节审计（Issue #208，spec §8.1 Q3=C 前端最小版）——AuditDialog 报告弹层契约测试
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/components/AuditDialog.tsx，必须匹配：
 *
 * 导出契约（类型名与字段对齐 spec §2.2 ChapterAuditReport 的 model_dump(mode='json')）：
 * - interface AuditFindingView {
 *     check_type: string;                      // word_count | character_drift | setting_drift | static_consistency
 *     severity: 'info' | 'warning' | 'error';
 *     message: string;
 *     suggestion?: string;
 *     ref_entity_name?: string;
 *     context?: string;
 *   }
 * - interface AuditReportView {
 *     chapter_id: string;
 *     chapter_title: string;
 *     status: 'pending' | 'accepted' | 'rejected';
 *     findings: AuditFindingView[];
 *     summary: string;
 *     degraded: boolean;
 *     created_at: string;
 *     confirmed_at: string | null;
 *   }
 * - interface AuditDialogProps {
 *     open: boolean; report: AuditReportView | null;
 *     loading: boolean; error: string | null;
 *     onClose: () => void;
 *     onConfirm: (action: 'accept' | 'reject', note: string) => void;
 *     confirming: boolean;
 *   }
 * - function AuditDialog(props: AuditDialogProps): JSX.Element | null
 *
 * 渲染契约：
 * - open=false → 返回 null（不渲染）
 * - open=true + report=null + loading=true → 加载态（data-testid="audit-dialog-loading"）
 * - open=true + report=null + error 非空 → 显示 error 文案（errorMessage 输出）+ 关闭按钮
 * - open=true + report → role="dialog"（或 aria-modal，测试用 getByRole('dialog') 定位）；
 *   章节标题为独立文本元素（文本 = chapter_title）；findings 按 severity 分组：
 *   error 组在前、warning、info 依次在后（document 文本顺序断言）；
 *   每个 finding 的 message 渲染为独立文本元素（断言用精确文本匹配）；
 *   suggestion 非空时显示；ref_entity_name 非空时显示；
 *   degraded=true → 显示降级提示（文案含「降级」）
 * - 确认按钮「接受」（accept）与「拒绝」（reject）：
 *   * 点击「接受」→ onConfirm('accept', '')
 *   * 点击「拒绝」→ 出现 note 输入框（textarea 或 input，data-testid="audit-note-input"）
 *     → 输入文字后再点「拒绝」→ onConfirm('reject', 输入的文字)
 *   * note 为空时直接再点「拒绝」→ onConfirm('reject', '')
 * - confirming=true → 「接受」「拒绝」两按钮均 disabled
 * - 关闭按钮（「关闭」）→ onClose
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts；测试环境默认语言 zh，直接断言中文）：
 * audit.accept='接受' / audit.reject='拒绝' / audit.close='关闭' /
 * audit.loading='审计中…' / audit.degraded（含「降级」字样）/
 * audit.errorTitle（错误标题，非必须）
 * severity 分组标题 / note 输入框占位文案由 GREEN 自定（本测试不锁）。
 *
 * RED 预期：./AuditDialog 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuditDialog } from './AuditDialog';

/** 契约结构镜像（GREEN 类型从组件导出；本文件内联镜像供测试播种） */
interface AuditFindingView {
  check_type: string;
  severity: 'info' | 'warning' | 'error';
  message: string;
  suggestion?: string;
  ref_entity_name?: string;
  context?: string;
}

interface AuditReportView {
  chapter_id: string;
  chapter_title: string;
  status: 'pending' | 'accepted' | 'rejected';
  findings: AuditFindingView[];
  summary: string;
  degraded: boolean;
  created_at: string;
  confirmed_at: string | null;
}

interface AuditDialogProps {
  open: boolean;
  report: AuditReportView | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (action: 'accept' | 'reject', note: string) => void;
  confirming: boolean;
}

/** 三 severity 齐备的报告（message 不含 ref_entity_name 字样，保证 ref 断言唯一） */
const report: AuditReportView = {
  chapter_id: 'c2',
  chapter_title: '第 3 章 龙的苏醒',
  status: 'pending',
  findings: [
    {
      check_type: 'setting_drift',
      severity: 'error',
      message: '明确矛盾：设定灵气枯竭，本章却写灵气充沛',
      suggestion: '改为灵气恢复的伏笔，或先铺垫',
      ref_entity_name: '灵气枯竭法则',
      context: '……',
    },
    {
      check_type: 'character_drift',
      severity: 'warning',
      message: '本章主角对同伴发怒，行为可能与人设冲突',
      suggestion: '',
      ref_entity_name: '李青焰',
      context: '……',
    },
    {
      check_type: 'word_count',
      severity: 'info',
      message: '本章 2,845 字，低于目标 3,000 字',
    },
  ],
  summary: '本章整体符合设定，一处角色行为值得斟酌',
  degraded: true,
  created_at: '2026-08-09T10:00:00Z',
  confirmed_at: null,
};

function renderDialog(overrides: Partial<AuditDialogProps> = {}) {
  const props: AuditDialogProps = {
    open: true,
    report: null,
    loading: false,
    error: null,
    onClose: vi.fn(),
    onConfirm: vi.fn(),
    confirming: false,
    ...overrides,
  };
  render(<AuditDialog {...props} />);
  return props;
}

describe('AuditDialog — 开合与状态', () => {
  it('open=false → 不渲染', () => {
    renderDialog({ open: false });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('open=true + loading → 加载态 testid', () => {
    renderDialog({ loading: true });
    expect(screen.getByTestId('audit-dialog-loading')).toBeInTheDocument();
  });

  it('open=true + report=null + error → 显示错误文案 + 关闭按钮触发 onClose', async () => {
    const user = userEvent.setup();
    const props = renderDialog({ error: 'Kernel unreachable' });
    expect(screen.getByText(/Kernel unreachable/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '关闭' }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });
});

describe('AuditDialog — 报告展示', () => {
  it('open=true + report → role=dialog + 章节标题', () => {
    renderDialog({ report });
    const dlg = screen.getByRole('dialog');
    expect(within(dlg).getByText('第 3 章 龙的苏醒')).toBeInTheDocument();
  });

  it('findings 全部 message 在场，error 组在前（document 顺序 error < warning < info）', () => {
    renderDialog({ report });
    expect(screen.getByText('明确矛盾：设定灵气枯竭，本章却写灵气充沛')).toBeInTheDocument();
    expect(screen.getByText('本章主角对同伴发怒，行为可能与人设冲突')).toBeInTheDocument();
    expect(screen.getByText('本章 2,845 字，低于目标 3,000 字')).toBeInTheDocument();

    const body = document.body.textContent ?? '';
    const err = body.indexOf('明确矛盾');
    const warn = body.indexOf('对同伴发怒');
    const info = body.indexOf('2,845 字');
    expect(err).toBeGreaterThanOrEqual(0);
    expect(warn).toBeGreaterThan(err);
    expect(info).toBeGreaterThan(warn);
  });

  it('suggestion 非空显示 + ref_entity_name 非空显示', () => {
    renderDialog({ report });
    expect(screen.getByText(/改为灵气恢复的伏笔/)).toBeInTheDocument();
    expect(screen.getByText(/李青焰/)).toBeInTheDocument();
    expect(screen.getByText(/灵气枯竭法则/)).toBeInTheDocument();
  });

  it('degraded=true → 降级提示（文案含「降级」）', () => {
    renderDialog({ report });
    expect(screen.getByText(/降级/)).toBeInTheDocument();
  });
});

describe('AuditDialog — 确认交互', () => {
  it('点击「接受」→ onConfirm(accept, 空备注)', async () => {
    const user = userEvent.setup();
    const props = renderDialog({ report });
    await user.click(screen.getByRole('button', { name: '接受' }));
    expect(props.onConfirm).toHaveBeenCalledTimes(1);
    expect(props.onConfirm).toHaveBeenCalledWith('accept', '');
  });

  it('点击「拒绝」→ note 输入框出现 → 输入 → 再点「拒绝」→ onConfirm(reject, 输入文字)', async () => {
    const user = userEvent.setup();
    const props = renderDialog({ report });
    await user.click(screen.getByRole('button', { name: '拒绝' }));
    const noteInput = screen.getByTestId('audit-note-input');
    await user.type(noteInput, '人设需再打磨');
    await user.click(screen.getByRole('button', { name: '拒绝' }));
    expect(props.onConfirm).toHaveBeenCalledTimes(1);
    expect(props.onConfirm).toHaveBeenCalledWith('reject', '人设需再打磨');
  });

  it('note 为空时点击「拒绝」也触发 onConfirm(reject, 空串)', async () => {
    const user = userEvent.setup();
    const props = renderDialog({ report });
    await user.click(screen.getByRole('button', { name: '拒绝' }));
    expect(screen.getByTestId('audit-note-input')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '拒绝' }));
    expect(props.onConfirm).toHaveBeenCalledTimes(1);
    expect(props.onConfirm).toHaveBeenCalledWith('reject', '');
  });

  it('confirming=true → 「接受」「拒绝」均 disabled', () => {
    renderDialog({ report, confirming: true });
    expect(screen.getByRole('button', { name: '接受' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '拒绝' })).toBeDisabled();
  });

  it('关闭按钮 → onClose', async () => {
    const user = userEvent.setup();
    const props = renderDialog({ report });
    await user.click(screen.getByRole('button', { name: '关闭' }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });
});
