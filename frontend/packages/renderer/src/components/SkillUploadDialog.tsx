/**
 * F40 #259 Skill 上传与绑定弹窗（spec §5.4 上传+绑定 / D1 拍板）：
 * 受控弹窗；真实 API 调用——上传走 useSkillsStore.uploadSkill，绑定走 useAgentsStore.bindSkill。
 * D1 铁律：绑定候选默认全部不勾选；内置 Agent 只读（checkbox disabled）。
 */
import { useEffect, useMemo, useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { errorMessage } from '../api/client';
import { parseSkillFrontmatter, SkillFrontmatterError } from '../lib/skill-frontmatter';
import type { SkillFrontmatter } from '../lib/skill-frontmatter';
import { useAgentsStore } from '../stores/agents';
import { useSkillsStore, type Skill } from '../stores/skills';

export interface SkillUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploaded?: (skill: Skill) => void;
}

export function SkillUploadDialog({ open, onOpenChange, onUploaded }: SkillUploadDialogProps) {
  const { t } = useI18n();
  const agents = useAgentsStore((s) => s.agents);
  const [content, setContent] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<number[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bindError, setBindError] = useState<string | null>(null);

  // 打开时重置表单并加载 Agent 候选（loadAgents 内部吞错 → 从 store.error 转本地错误）
  useEffect(() => {
    if (!open) return;
    setContent('');
    setSearch('');
    setSelected([]);
    setSubmitting(false);
    setError(null);
    setBindError(null);
    void (async () => {
      await useAgentsStore.getState().loadAgents();
      const storeError = useAgentsStore.getState().error;
      if (storeError) setBindError(storeError);
    })();
  }, [open]);

  // ESC 关闭（document 级监听；尊重已 preventDefault 的 Escape）
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  // 实时 frontmatter 解析预览（空内容 → 无预览；非法 → 上传禁用）
  const parsed = useMemo<{ fm: SkillFrontmatter | null; fmError: string | null }>(() => {
    if (content.trim() === '') return { fm: null, fmError: null };
    try {
      return { fm: parseSkillFrontmatter(content), fmError: null };
    } catch (err) {
      return { fm: null, fmError: err instanceof SkillFrontmatterError ? err.message : errorMessage(err) };
    }
  }, [content]);

  const filteredAgents = agents.filter((agent) => agent.name.includes(search.trim()));
  const nonBuiltinIds = agents.filter((agent) => !agent.builtin).map((agent) => agent.id);
  const allNonBuiltinSelected =
    nonBuiltinIds.length > 0 && nonBuiltinIds.every((id) => selected.includes(id));
  const canUpload = parsed.fm !== null && !submitting;

  const toggleAgent = (agentId: number) => {
    setSelected((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId],
    );
  };

  // 「应用到全部」toggle：已全选非内置 → 取消；否则勾选全部非内置（内置保持禁用）
  const handleBindAll = () => {
    if (allNonBuiltinSelected) {
      setSelected((prev) => prev.filter((id) => !nonBuiltinIds.includes(id)));
    } else {
      setSelected((prev) => Array.from(new Set([...prev, ...nonBuiltinIds])));
    }
  };

  // 提交流程（async 链）：POST /skills → 勾选非空 Agent 逐个 PATCH；任一步失败不关闭
  const handleSubmit = async () => {
    if (!parsed.fm || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const newSkill = await useSkillsStore.getState().uploadSkill(content);
      for (const agentId of selected) {
        try {
          // F41 合入后 agents store 用 updateAgent 全字段替换（无 bindSkill）；追加语义：
          // 读当前 skill_ids（字符串化）→ 追加新 id → PATCH（spec §2.4/§5.4 绑定产物）
          const agent = useAgentsStore.getState().agents.find((a) => a.id === agentId);
          const skillIds = agent ? [...agent.skill_ids, String(newSkill.id)] : [String(newSkill.id)];
          await useAgentsStore.getState().updateAgent(agentId, { skill_ids: skillIds });
        } catch (err) {
          // 上传成功但绑定失败：提示「上传成功，绑定失败」+ 已上传 skill 不回滚
          setError(`${t('skill.bindFail')}：${errorMessage(err)}`);
          return;
        }
      }
      onOpenChange(false);
      onUploaded?.(newSkill);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('skill.upload')}
        data-testid="skill-upload-dialog"
        className="max-h-[85vh] w-[560px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('skill.upload')}</h2>

        {/* 上传区：SKILL.md 全文 + frontmatter 实时预览 */}
        <div className="mt-4">
          <label htmlFor="skill-upload-content" className="text-[12px] text-ink-2">
            {t('skill.content')}
          </label>
          <textarea
            id="skill-upload-content"
            data-testid="skill-upload-content"
            aria-label={t('skill.content')}
            rows={10}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="---\nname: my-skill\ndescription: 描述\n---"
            className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 font-mono text-[12px] text-ink outline-none focus:border-accent"
          />
        </div>

        {content.trim() !== '' && (
          <div
            data-testid="skill-upload-preview"
            className="mt-2 space-y-1 rounded-md border border-line bg-surface-2 p-3 text-[12px]"
          >
            {parsed.fm ? (
              <>
                <div data-testid="skill-upload-preview-name">{parsed.fm.name}</div>
                <div data-testid="skill-upload-preview-desc">{parsed.fm.description}</div>
                {parsed.fm.tags.length > 0 && (
                  <div data-testid="skill-upload-preview-tags">{parsed.fm.tags.join(', ')}</div>
                )}
              </>
            ) : (
              <div data-testid="skill-upload-preview-error" className="text-err">
                {t('skill.fmError')}：{parsed.fmError}
              </div>
            )}
          </div>
        )}

        {/* 绑定区（D1：默认不勾选 + 可搜索 + 应用到全部；内置禁用） */}
        <div className="mt-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-[13px] font-medium text-ink">{t('skill.bindTitle')}</h3>
              <p className="mt-0.5 text-[11px] text-ink-3">{t('skill.bindHint')}</p>
            </div>
            <button
              type="button"
              data-testid="skill-bind-all"
              className="shrink-0 rounded border border-line px-2.5 py-1 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={handleBindAll}
            >
              {t('skill.bindAll')}
            </button>
          </div>

          <input
            type="text"
            data-testid="skill-bind-search"
            aria-label={t('skill.searchAgent')}
            placeholder={t('skill.searchAgent')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="mt-2 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] text-ink outline-none focus:border-accent"
          />

          {bindError ? (
            <div data-testid="skill-bind-error" className="mt-2 text-[12px] text-err">
              {bindError}
            </div>
          ) : (
            <div className="mt-2 max-h-44 space-y-1.5 overflow-y-auto">
              {filteredAgents.map((agent) => (
                <label
                  key={agent.id}
                  data-testid={`skill-bind-agent-${agent.id}`}
                  className="flex items-center gap-2 rounded border border-line px-2.5 py-1.5 text-[12px] text-ink"
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(agent.id)}
                    disabled={agent.builtin}
                    onChange={() => toggleAgent(agent.id)}
                  />
                  <span className="min-w-0 flex-1 truncate">{agent.name}</span>
                  {agent.builtin && (
                    <span className="shrink-0 rounded-full border border-line px-2 py-0.5 text-[10px] text-ink-3">
                      {t('skill.builtinBadge')}
                    </span>
                  )}
                </label>
              ))}
            </div>
          )}
        </div>

        {error && (
          <div data-testid="skill-upload-error" className="mt-3 text-[12px] text-err">
            {error}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            data-testid="skill-upload-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            data-testid="skill-upload-submit"
            disabled={!canUpload}
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void handleSubmit()}
          >
            {t('skill.uploadBtn')}
          </button>
        </div>
      </div>
    </div>
  );
}
