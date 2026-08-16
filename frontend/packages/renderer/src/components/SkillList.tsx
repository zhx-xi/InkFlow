/**
 * F40 #259 Skill 管理列表（spec §5.4 管理列表 / §5.6 删除保护）：
 * 面板级组件（无 props），自管理数据：挂载时 loadSkills + loadAgents；
 * 删除复用共享 ConfirmDialog（testidPrefix='skill-confirm'，danger）。
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useAgentsStore } from '../stores/agents';
import { useSkillsStore, type Skill } from '../stores/skills';
import { ConfirmDialog } from './ConfirmDialog';
import { SkillUploadDialog } from './SkillUploadDialog';

export function SkillList() {
  const { t, lang } = useI18n();
  const skills = useSkillsStore((s) => s.skills);
  const loading = useSkillsStore((s) => s.loading);
  const skillsError = useSkillsStore((s) => s.error);
  const [confirming, setConfirming] = useState<Skill | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);

  // 挂载时加载列表 + Agent 候选（反查引用名兜底；列表端点 agent_ids 已含 name）
  useEffect(() => {
    void useSkillsStore.getState().loadSkills();
    void useAgentsStore.getState().loadAgents();
  }, []);

  // deleteSkill 不 rethrow（失败 → store.error + 列表不变）；确认后关闭弹窗
  const handleConfirmDelete = async () => {
    if (!confirming) return;
    const target = confirming;
    await useSkillsStore.getState().deleteSkill(target.id);
    setConfirming(null);
  };

  const namesText = (skill: Skill): string =>
    skill.agent_ids.map((ref) => ref.name).join(lang === 'en' ? ', ' : '、');

  const confirmMessage: ReactNode = confirming
    ? confirming.agent_ids.length > 0
      ? (
          <span data-testid="skill-confirm-message">
            {t('skill.deleteReferenced', {
              n: confirming.agent_ids.length,
              names: namesText(confirming),
            })}
          </span>
        )
      : t('skill.deleteConfirm')
    : '';

  return (
    <section data-testid="skill-list" className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-[17px] font-semibold">{t('skill.listTitle')}</h2>
        <button
          type="button"
          data-testid="skill-add-btn"
          className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={() => setUploadOpen(true)}
        >
          {t('skill.add')}
        </button>
      </div>

      {skillsError && (
        <div data-testid="skill-list-error" className="text-[13px] text-err">
          {skillsError}
        </div>
      )}

      {loading && skills.length === 0 ? (
        <div className="text-[13px] text-ink-3">{t('common.loading')}</div>
      ) : skills.length === 0 ? (
        <div data-testid="skill-empty" className="text-[13px] text-ink-3">
          {t('skill.empty')}
        </div>
      ) : (
        <div className="space-y-3">
          {skills.map((skill) => (
            <div
              key={skill.id}
              data-testid={`skill-card-${skill.id}`}
              className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface p-4 shadow-card"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span data-testid="skill-card-name" className="truncate text-[14px] font-medium text-ink">
                    {skill.name}
                  </span>
                  <span
                    data-testid={`skill-source-${skill.source === 'builtin' ? 'builtin' : 'user'}-${skill.id}`}
                    className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-2"
                  >
                    {skill.source === 'builtin' ? t('skill.builtin') : t('skill.userUpload')}
                  </span>
                </div>
                {skill.description && (
                  <p data-testid="skill-card-desc" className="mt-1 truncate text-[12px] text-ink-3">
                    {skill.description}
                  </p>
                )}
                {skill.agent_ids.length > 0 && (
                  <span
                    data-testid={`skill-refs-${skill.id}`}
                    className="mt-2 inline-block rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-2"
                  >
                    {t('skill.refs', { n: skill.agent_ids.length, names: namesText(skill) })}
                  </span>
                )}
              </div>
              {skill.source === 'user_upload' && (
                <button
                  type="button"
                  data-testid={`skill-delete-${skill.id}`}
                  aria-label={`${t('lib.delete')} ${skill.name}`}
                  className="shrink-0 rounded border border-line px-2.5 py-1 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setConfirming(skill)}
                >
                  {t('lib.delete')}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {uploadOpen && (
        <SkillUploadDialog
          open
          onOpenChange={setUploadOpen}
          onUploaded={() => void useSkillsStore.getState().loadSkills()}
        />
      )}

      {confirming && (
        <ConfirmDialog
          open
          title={t('skill.deleteTitle', { name: confirming.name })}
          message={confirmMessage}
          confirmText={t('lib.delete.ok')}
          danger
          testidPrefix="skill-confirm"
          onConfirm={() => void handleConfirmDelete()}
          onOpenChange={(v) => {
            if (!v) setConfirming(null);
          }}
        />
      )}
    </section>
  );
}
