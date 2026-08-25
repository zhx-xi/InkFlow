/**
 * T2 风格检测（StyleAnalyzeDialog）报告弹层契约测试
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/components/StyleAnalyzeDialog.tsx，必须匹配：
 * - interface StyleReportDto（与 src/api/style.ts 同构：
 *     project_id / source / fingerprint / ai_trace / lexical；类型可从 api 模块 re-export）
 * - function StyleAnalyzeDialog(props: {
 *     open: boolean; report: StyleReportDto | null;
 *     loading: boolean; error: string | null; onClose: () => void;
 *   }): JSX.Element | null
 *
 * 渲染契约（镜像 AuditDialog 三态弹层，accept/reject 换成关闭）：
 * - 弹层容器 data-testid="style-analyze-dialog"；open=false → 返回 null（不渲染）
 * - open=true + loading=true + report=null → 加载态 data-testid="style-dialog-loading"，
 *   文案含「分析中」
 * - open=true + report=null + error 非空 → data-testid="style-dialog-error"
 *   显示 error 文案（errorMessage 输出）+ 关闭按钮（「关闭」）→ onClose
 * - open=true + report → data-testid="style-dialog-report"，含三个区：
 *   * 指纹区 data-testid="style-fingerprint"：
 *     句子均值 style-fp-sentence / 段落均值 style-fp-paragraph /
 *     对话占比 style-fp-dialogue / 词汇丰富度 style-fp-vocab
 *     （数值断言用 toHaveTextContent 含数字子串即可，不必精确）+ top_words 词频列表词条在场
 *   * AI 痕迹区 data-testid="style-ai-trace"：
 *     AI 得分 style-ai-score（含数字子串）/ 判定 style-verdict（非空文本）/ evidence 列表
 *   * 词汇区 data-testid="style-lexical"：unique_words / total_words / stopword_ratio 数值
 * - 关闭按钮 data-testid="style-dialog-close"（报告态）→ onClose
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts；测试环境默认语言 zh，直接断言中文）：
 * write.style.loading（含「分析中」）/ write.style.close='关闭'；各区标题由 GREEN 自定（本测试不锁）。
 *
 * RED 预期：./StyleAnalyzeDialog 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StyleAnalyzeDialog } from './StyleAnalyzeDialog';

/** 契约结构镜像（GREEN 类型从组件/api 模块导出；本文件内联镜像供测试播种） */
interface StyleWordFrequencyDto {
  word: string;
  count: number;
}

interface StyleFingerprintDto {
  sentences: number;
  paragraphs: number;
  char_count: number;
  sentence_avg_len: number;
  paragraph_avg_len: number;
  ellipsis_density: number;
  dialogue_ratio: number;
  vocabulary_richness: number;
  top_words: StyleWordFrequencyDto[];
}

interface StyleAITraceDto {
  ai_score: number;
  verdict: 'likely_human' | 'uncertain' | 'likely_ai';
  evidence: string[];
}

interface StyleLexicalDto {
  unique_words: number;
  total_words: number;
  stopword_ratio: number;
}

interface StyleReportDto {
  project_id: string;
  source: string;
  fingerprint: StyleFingerprintDto;
  ai_trace: StyleAITraceDto;
  lexical: StyleLexicalDto;
}

interface StyleAnalyzeDialogProps {
  open: boolean;
  report: StyleReportDto | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

const seedReport: StyleReportDto = {
  project_id: 'p1',
  source: 'chapter:c1',
  fingerprint: {
    sentences: 12,
    paragraphs: 4,
    char_count: 600,
    sentence_avg_len: 22.4,
    paragraph_avg_len: 3.1,
    ellipsis_density: 0.02,
    dialogue_ratio: 0.38,
    vocabulary_richness: 0.42,
    top_words: [
      { word: '雨', count: 8 },
      { word: '城门', count: 5 },
    ],
  },
  ai_trace: {
    ai_score: 0.28,
    verdict: 'likely_human',
    evidence: ['各特征得分均低于 0.5，无明显 AI 特征'],
  },
  lexical: {
    unique_words: 120,
    total_words: 280,
    stopword_ratio: 0.12,
  },
};

function renderDialog(overrides: Partial<StyleAnalyzeDialogProps> = {}) {
  const props: StyleAnalyzeDialogProps = {
    open: true,
    report: null,
    loading: false,
    error: null,
    onClose: vi.fn(),
    ...overrides,
  };
  render(<StyleAnalyzeDialog {...props} />);
  return props;
}

describe('StyleAnalyzeDialog — 开合与状态', () => {
  it('open=false → 不渲染（null）', () => {
    renderDialog({ open: false });
    expect(screen.queryByTestId('style-analyze-dialog')).not.toBeInTheDocument();
  });

  it('open=true + loading + report=null → 加载态（文案含「分析中」）', () => {
    renderDialog({ loading: true });
    const loading = screen.getByTestId('style-dialog-loading');
    expect(loading).toBeInTheDocument();
    expect(within(loading).getByText(/分析中/)).toBeInTheDocument();
  });

  it('open=true + report=null + error → 错误文案 + 关闭按钮触发 onClose', async () => {
    const user = userEvent.setup();
    const props = renderDialog({ error: 'Kernel unreachable' });
    const errorBox = screen.getByTestId('style-dialog-error');
    expect(within(errorBox).getByText(/Kernel unreachable/)).toBeInTheDocument();
    await user.click(within(errorBox).getByRole('button', { name: '关闭' }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });
});

describe('StyleAnalyzeDialog — 报告展示', () => {
  it('open=true + report → 弹层容器 + 三个区在场', () => {
    renderDialog({ report: seedReport });
    expect(screen.getByTestId('style-analyze-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('style-dialog-report')).toBeInTheDocument();
    expect(screen.getByTestId('style-fingerprint')).toBeInTheDocument();
    expect(screen.getByTestId('style-ai-trace')).toBeInTheDocument();
    expect(screen.getByTestId('style-lexical')).toBeInTheDocument();
  });

  it('指纹区：句子/段落均值 + 对话占比 + 词汇丰富度 + top_words 词条', () => {
    renderDialog({ report: seedReport });
    const fp = screen.getByTestId('style-fingerprint');
    expect(within(fp).getByTestId('style-fp-sentence')).toHaveTextContent('22.4');
    expect(within(fp).getByTestId('style-fp-paragraph')).toHaveTextContent('3.1');
    expect(within(fp).getByTestId('style-fp-dialogue')).toHaveTextContent('0.38');
    expect(within(fp).getByTestId('style-fp-vocab')).toHaveTextContent('0.42');
    expect(within(fp).getByText('雨')).toBeInTheDocument();
    expect(within(fp).getByText('城门')).toBeInTheDocument();
  });

  it('AI 痕迹区：得分 + 判定（非空）+ evidence 列表', () => {
    renderDialog({ report: seedReport });
    const trace = screen.getByTestId('style-ai-trace');
    expect(within(trace).getByTestId('style-ai-score')).toHaveTextContent('0.28');
    const verdict = within(trace).getByTestId('style-verdict');
    expect(verdict).toBeInTheDocument();
    expect(verdict.textContent?.trim().length ?? 0).toBeGreaterThan(0);
    expect(within(trace).getByText('各特征得分均低于 0.5，无明显 AI 特征')).toBeInTheDocument();
  });

  it('词汇区：unique / total / stopword_ratio 数值', () => {
    renderDialog({ report: seedReport });
    const lexical = screen.getByTestId('style-lexical');
    expect(within(lexical).getByText(/120/)).toBeInTheDocument();
    expect(within(lexical).getByText(/280/)).toBeInTheDocument();
    expect(within(lexical).getByText(/0\.12/)).toBeInTheDocument();
  });
});

describe('StyleAnalyzeDialog — 关闭交互', () => {
  it('报告态：点击关闭按钮（style-dialog-close）→ onClose', async () => {
    const user = userEvent.setup();
    const props = renderDialog({ report: seedReport });
    await user.click(screen.getByTestId('style-dialog-close'));
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it('进行中反馈：loading=true 且 report=null → style-dialog-loading（不渲染报告）', () => {
    renderDialog({ loading: true, report: null });
    expect(screen.getByTestId('style-dialog-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('style-dialog-report')).not.toBeInTheDocument();
  });
});
