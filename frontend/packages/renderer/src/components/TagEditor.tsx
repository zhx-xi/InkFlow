/** 角色分组标签编辑器（F43 P1，specs/f43-setting-library-gui/spec.md v1.1 §2.3/§5.2，D2）：
 * wiki 风格多选——已选 chips（× 移除）+ 输入框（回车/逗号创建，strip 去空去重）+ 建议标签按钮。
 * 建议标签来源 = 父级聚合的当前项目角色 extra.groups 并集（数据驱动，D-13）。
 * testid 契约：lib-tag-input / lib-tag-chip-<tag>（× 按钮同 chip 内）/ lib-tag-suggest-<tag>。 */
import { useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Plus } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';

export interface TagEditorProps {
  /** 当前已选标签（父级维护 state） */
  selected: string[];
  /** 建议标签（当前项目角色 extra.groups 并集；空数组 = 不渲染建议区，E16） */
  suggestions: string[];
  /** 变更回调（父级 setState） */
  onChange: (tags: string[]) => void;
  testidPrefix?: string;
}

const INPUT_CLS =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent';

export function TagEditor({
  selected,
  suggestions,
  onChange,
  testidPrefix = 'lib',
}: TagEditorProps) {
  const { t } = useI18n();
  const [input, setInput] = useState('');

  /** strip 去空去重后追加（E15：空/重复忽略，去重保序） */
  const addTag = (raw: string) => {
    const tag = raw.trim();
    if (!tag || selected.includes(tag)) return;
    onChange([...selected, tag]);
  };

  const removeTag = (tag: string) => {
    onChange(selected.filter((x) => x !== tag));
  };

  const addSuggestion = (tag: string) => {
    if (!selected.includes(tag)) onChange([...selected, tag]);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // 回车 / 逗号创建（E15 strip 后空 → 不创建；重复 → 忽略）
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag(input);
      setInput('');
    }
  };

  return (
    <div className="flex flex-col gap-1.5 text-[13px]">
      <span className="text-[13px]">{t('lib.tags.label')}</span>

      {/* 已选 chips（× 移除按钮在 chip 内，R5 契约） */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((tag) => (
            <span
              key={tag}
              data-testid={`${testidPrefix}-tag-chip-${tag}`}
              className="inline-flex items-center gap-1 rounded-full bg-surface-3 px-2.5 py-0.5 text-[12px] text-ink"
            >
              {tag}
              <button
                type="button"
                aria-label={tag}
                className="flex h-4 w-4 items-center justify-center rounded-full text-ink-3 transition duration-150 hover:bg-surface hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => removeTag(tag)}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <input
        data-testid={`${testidPrefix}-tag-input`}
        aria-label={t('lib.tags.label')}
        className={INPUT_CLS}
        placeholder={t('lib.tags.placeholder')}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
      />

      {/* 建议标签（点击追加，重复忽略；空 → 无建议区，E16） */}
      {suggestions.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12px] text-ink-2">{t('lib.tags.suggest')}</span>
          {suggestions.map((tag) => (
            <button
              key={tag}
              type="button"
              data-testid={`${testidPrefix}-tag-suggest-${tag}`}
              className={cn(
                'inline-flex items-center gap-1 rounded-full border border-dashed border-line px-2.5 py-0.5 text-[12px] text-ink-2',
                'transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              )}
              onClick={() => addSuggestion(tag)}
            >
              <Plus className="h-3 w-3" aria-hidden="true" />
              {tag}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
