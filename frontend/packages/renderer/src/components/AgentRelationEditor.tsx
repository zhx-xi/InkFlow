/** F46 #270：Agent 关联关系编辑器（spec §5.2 Q3=A 列表式编辑 + 只读 DAG 预览）：
 *  关系列表增删 + 新增选择器（from/to/type + 自环/重复预检）+ 只读 DAG 节点-边预览；
 *  变更走 setConfig + onConfigChange（F42 即改即存 PATCH 链路） */
import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import { useAgentStore } from '../stores/agent';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

export interface AgentRelationEditorProps {
  /** 变更回调（#105 🔴-2：AgentPanel 即改即存 PATCH；不传则仅更新本地 store） */
  onConfigChange?: () => void;
}

/** F46 #270：内置角色字段（下拉/节点数据源 = 内置 4 + agent_roles keys，spec §5.2） */
const ROLE_FIELDS = ['agent_architect', 'agent_writer', 'agent_auditor', 'agent_reviser'];
/** F46 #270：边类型三选（spec §2.1：sequential/data/conditional） */
const RELATION_TYPES = ['sequential', 'data', 'conditional'];

/** 去 agent_ 前缀（DAG 节点/边 testid 用，spec §1.2.2） */
function bareRole(field: string): string {
  return field.replace(/^agent_/, '');
}

/** 边样式类契约：sequential=edge-seq / data=edge-data / conditional=edge-cond（测试断言 className） */
function edgeClass(type: string): string {
  if (type === 'data') return 'edge-data';
  if (type === 'conditional') return 'edge-cond';
  return 'edge-seq';
}

export function AgentRelationEditor({ onConfigChange }: AgentRelationEditorProps = {}) {
  const { t } = useI18n();
  const config = useAgentStore((s) => s.config);
  const setConfig = useAgentStore((s) => s.setConfig);

  // F46 #270：角色数据源 = 内置 4 + agent_roles keys（自定义角色）
  const roleFields = [...ROLE_FIELDS, ...Object.keys(config.agent_roles ?? {})];
  const relations = config.agent_relations ?? [];

  const [adding, setAdding] = useState(false);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [type, setType] = useState('sequential');
  const [error, setError] = useState<string | null>(null);

  const resetPicker = () => {
    setAdding(false);
    setFrom('');
    setTo('');
    setType('sequential');
    setError(null);
  };

  const confirm = () => {
    // 前端预检（与后端 422 语义镜像，spec §5.2）：自环 / 重复边 → 不提交
    if (from === to) {
      setError(t('ag.relationSelfLoop'));
      return;
    }
    if (relations.some((r) => r.from === from && r.to === to)) {
      setError(t('ag.relationDuplicate'));
      return;
    }
    setConfig({ agent_relations: [...relations, { from, to, type }] });
    onConfigChange?.();
    resetPicker();
  };

  const remove = (idx: number) => {
    setConfig({ agent_relations: relations.filter((_, i) => i !== idx) });
    onConfigChange?.();
  };

  return (
    <>
      <section
        data-testid="agent-relation-editor"
        className="mt-4 rounded-lg border border-line bg-surface-2 p-4"
      >
        <h3 className="text-[13px] font-semibold">{t('ag.relationTitle')}</h3>
        {relations.length === 0 ? (
          <p data-testid="agent-relation-empty" className="mt-2 text-[12px] text-ink-3">
            {t('ag.relationEmpty')}
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {relations.map((r, idx) => (
              <li
                key={`${r.from}-${r.to}-${idx}`}
                data-testid={`agent-relation-row-${idx}`}
                className="flex items-center gap-2 rounded bg-surface px-2 py-1 text-[12px]"
              >
                <span>
                  {r.from} → {bareRole(r.to)} [{r.type}]
                </span>
                <button
                  type="button"
                  data-testid={`agent-relation-del-${idx}`}
                  aria-label={t('ag.relationDel')}
                  onClick={() => remove(idx)}
                  className="ml-auto flex h-5 w-5 items-center justify-center rounded border border-line text-ink-3 hover:bg-surface-3"
                >
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
        {!adding ? (
          <button
            type="button"
            data-testid="agent-relation-add"
            onClick={() => {
              setAdding(true);
              setError(null);
            }}
            className="mt-3 flex items-center gap-1 rounded border border-line px-2 py-1 text-[12px] text-ink-3 hover:bg-surface-3"
          >
            <Plus className="h-3 w-3" aria-hidden="true" />
            {t('ag.relationAdd')}
          </button>
        ) : (
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-[12px] text-ink-3">
              {t('ag.relationFrom')}
              <Select
                value={from}
                onValueChange={(v) => {
                  setFrom(v);
                  setError(null);
                }}
              >
                <SelectTrigger data-testid="agent-relation-from-select" className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roleFields.map((field) => (
                    <SelectItem key={field} value={field}>
                      {field}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-ink-3">
              {t('ag.relationTo')}
              <Select
                value={to}
                onValueChange={(v) => {
                  setTo(v);
                  setError(null);
                }}
              >
                <SelectTrigger data-testid="agent-relation-to-select" className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roleFields.map((field) => (
                    <SelectItem key={field} value={field}>
                      {field}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-ink-3">
              {t('ag.relationType')}
              <Select
                value={type}
                onValueChange={(v) => {
                  setType(v);
                  setError(null);
                }}
              >
                <SelectTrigger data-testid="agent-relation-type-select" className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RELATION_TYPES.map((relationType) => (
                    <SelectItem key={relationType} value={relationType}>
                      {relationType}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <button
              type="button"
              data-testid="agent-relation-confirm"
              onClick={confirm}
              className="flex h-9 items-center rounded-md bg-accent px-3 text-[12px] text-accent-ink hover:opacity-90"
            >
              {t('ag.relationConfirm')}
            </button>
            {error && (
              <p data-testid="agent-relation-error" className="w-full text-[12px] text-warn">
                {error}
              </p>
            )}
            {type === 'conditional' && (
              <p data-testid="agent-relation-cond-hint" className="w-full text-[11px] text-ink-3">
                {t('ag.relationCondHint')}
              </p>
            )}
          </div>
        )}
      </section>
      {/* 只读 DAG 预览（spec §1.2.2 + §5.2 独立区）：节点 = 角色集合；边 = agent_relations，无任何交互 */}
      <div data-testid="agent-relation-dag-preview" className="mt-3 rounded bg-surface p-3">
        <h4 className="text-[12px] font-semibold">{t('ag.relationPreview')}</h4>
        <div className="mt-2 flex flex-wrap gap-2">
          {roleFields.map((field) => (
            <span
              key={field}
              data-testid={`agent-relation-dag-node-${bareRole(field)}`}
              className="rounded border border-line bg-surface-2 px-2 py-1 text-[11px] text-ink"
            >
              {bareRole(field)}
            </span>
          ))}
        </div>
        {relations.length > 0 && (
          <div className="mt-2 space-y-1">
            {relations.map((r, idx) => (
              <div
                key={`${r.from}-${r.to}-${idx}`}
                data-testid={`agent-relation-dag-edge-${bareRole(r.from)}-${bareRole(r.to)}`}
                className={`${edgeClass(r.type)} flex items-center gap-1 text-[11px] text-ink-3`}
              >
                <span>
                  {bareRole(r.from)} → {bareRole(r.to)}
                </span>
                <span className="rounded bg-surface-3 px-1 text-[10px]">{r.type}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
