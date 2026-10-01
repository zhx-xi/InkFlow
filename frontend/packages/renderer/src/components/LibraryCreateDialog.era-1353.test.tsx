/**
 * #1353 时间线事件对话框「纪元」字段 —— 组件级契约（LibraryCreateDialog）。
 *
 * 【spec 依据】specs/f12-timeline/spec.md §2.8 E1/E2/E4（承载键 + 成对语义）
 *            + specs/f19-gui/timeline.md §2（创建/编辑对话框行）。
 *
 * 【契约（GREEN 必须提供）】
 * - cat="timeline" 时新增两个字段：`library-create-era`（纪元轴名）
 *   + `library-create-era-value`（纪元内数值）；其他分类不渲染
 * - 保存 payload：`era` 去空白写入；`era_value` 数值（有限）→ number；
 *   空 → `""`（= 清除轴内值/无轴内值）；非数值字符串原样透传（后端 422 兜底）
 * - **编辑模式预填**：`editing.extra.era` / `editing.extra.era_value`
 * - **向后兼容**：不带纪元时 payload 的 era 为 `""`（后端 `era=""` = 不设纪元/清除，
 *   与既有行为一致 —— 既有 timeline payload 用例（title/time_display/description）不破）
 *
 * 【RED 预期】`library-create-era` / `library-create-era-value` 不存在 → getByTestId FAIL；
 * 零 SyntaxError / ReferenceError / TypeError。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryCreateDialog, type LibraryItemDTO } from './LibraryCreateDialog';
import { useThemeStore } from '../stores/theme';

const onSave = vi.fn();

function renderTimelineDialog(editing: LibraryItemDTO | null = null) {
  return render(
    <LibraryCreateDialog
      open
      cat="timeline"
      editing={editing}
      onSave={onSave}
      onOpenChange={() => {}}
    />,
  );
}

beforeEach(() => {
  onSave.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1353 时间线对话框纪元字段', () => {
  it('D1 timeline 分类渲染纪元 + 纪元内数值两个字段', () => {
    renderTimelineDialog();

    expect(screen.getByTestId('library-create-era')).toBeTruthy();
    expect(screen.getByTestId('library-create-era-value')).toBeTruthy();
  });

  it('D2 保存 payload：era 去空白 + era_value 转数值', async () => {
    renderTimelineDialog();
    const user = userEvent.setup();

    await user.type(screen.getByTestId('library-create-name'), '事件甲');
    await user.type(screen.getByTestId('library-create-era'), '  青元历  ');
    await user.type(screen.getByTestId('library-create-era-value'), '317.5');
    await user.click(screen.getByTestId('library-create-save'));

    expect(onSave).toHaveBeenCalledTimes(1);
    const body = onSave.mock.calls[0][0] as Record<string, unknown>;
    expect(body.title).toBe('事件甲');
    expect(body.era).toBe('青元历');
    expect(body.era_value).toBe(317.5);
  });

  it('D3 纪元内数值留空 → payload era_value 为 ""（无轴内值 / 清除）', async () => {
    renderTimelineDialog();
    const user = userEvent.setup();

    await user.type(screen.getByTestId('library-create-name'), '事件甲');
    await user.type(screen.getByTestId('library-create-era'), '青元历');
    await user.click(screen.getByTestId('library-create-save'));

    const body = onSave.mock.calls[0][0] as Record<string, unknown>;
    expect(body.era).toBe('青元历');
    expect(body.era_value).toBe('');
  });

  it('D4 编辑模式预填 extra.era / extra.era_value', () => {
    renderTimelineDialog({
      id: 'ev1',
      title: '事件甲',
      time_display: '青元历 317 年秋',
      extra: { era: '青元历', era_value: 317.5 },
    });

    expect((screen.getByTestId('library-create-era') as HTMLInputElement).value).toBe('青元历');
    expect((screen.getByTestId('library-create-era-value') as HTMLInputElement).value).toBe('317.5');
  });

  it('D5 非数值纪元内数值原样透传字符串（交后端 422 兜底，不静默丢弃）', async () => {
    renderTimelineDialog();
    const user = userEvent.setup();

    await user.type(screen.getByTestId('library-create-name'), '事件甲');
    await user.type(screen.getByTestId('library-create-era'), '青元历');
    await user.type(screen.getByTestId('library-create-era-value'), '甲子');
    await user.click(screen.getByTestId('library-create-save'));

    const body = onSave.mock.calls[0][0] as Record<string, unknown>;
    expect(body.era).toBe('青元历');
    expect(body.era_value).toBe('甲子');
  });

  it('D6 非 timeline 分类不渲染纪元字段（零外溢）', () => {
    render(
      <LibraryCreateDialog
        open
        cat="characters"
        editing={null}
        onSave={onSave}
        onOpenChange={() => {}}
      />,
    );

    expect(screen.queryByTestId('library-create-era')).toBeNull();
    expect(screen.queryByTestId('library-create-era-value')).toBeNull();
  });
});
