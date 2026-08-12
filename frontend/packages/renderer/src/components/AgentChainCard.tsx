/** 写作 Agent 链（spec §4.2.3）：Architect/Writer/Auditor/Reviser 四行开关 ↔ config.agent_*；
 *  #225 三态语义：null=关闭（禁用角色）；字符串=开启且指定模型；
 *  "__default__"（AGENT_DEFAULT_SENTINEL）=跟随默认（预留，前端不暴露中间态 UI） */
import { useEffect } from 'react';
import { ClipboardCheck, Network, PenLine, RefreshCw, type LucideIcon } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import { useAgentStore } from '../stores/agent';
import { selectChatModelOptions, useModelsStore } from '../stores/models';
import { AGENT_DEFAULT_SENTINEL, type ProjectConfig } from '../stores/project';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Switch } from './ui/switch';

type AgentField = 'agent_architect' | 'agent_writer' | 'agent_auditor' | 'agent_reviser';

const AGENT_ROLES: Array<{ field: AgentField; nameKey: string; descKey: string; icon: LucideIcon }> = [
  { field: 'agent_architect', nameKey: 'ag.architect', descKey: 'ag.architectDesc', icon: Network },
  { field: 'agent_writer', nameKey: 'ag.writer', descKey: 'ag.writerDesc', icon: PenLine },
  { field: 'agent_auditor', nameKey: 'ag.auditor', descKey: 'ag.auditorDesc', icon: ClipboardCheck },
  { field: 'agent_reviser', nameKey: 'ag.reviser', descKey: 'ag.reviserDesc', icon: RefreshCw },
];

/** F42 #269：默认模板拓扑（与后端默认模板槽位一致：architect=0/writer=1/auditor=2/reviser=3）；
 *  agent_order 空/undefined 时仅用于显示与首次移动时显式化（B1 默认模板模式） */
const DEFAULT_AGENT_ORDER: string[][] = [
  ['agent_architect'],
  ['agent_writer'],
  ['agent_auditor'],
  ['agent_reviser'],
];

/** 角色 → 默认槽位（开启角色时写入 agent_order 的目标槽位，spec §5.3/M6） */
const DEFAULT_SLOTS: Record<AgentField, number> = {
  agent_architect: 0,
  agent_writer: 1,
  agent_auditor: 2,
  agent_reviser: 3,
};

export interface AgentChainCardProps {
  /** 开关变更回调（#105 🔴-2：AgentPanel 即改即存 PATCH；不传则仅更新本地 store） */
  onConfigChange?: () => void;
}

function agentPatch(field: AgentField, value: string | null | undefined): Partial<ProjectConfig> {
  switch (field) {
    case 'agent_architect':
      return { agent_architect: value };
    case 'agent_writer':
      return { agent_writer: value };
    case 'agent_auditor':
      return { agent_auditor: value };
    case 'agent_reviser':
      return { agent_reviser: value };
    default:
      return {};
  }
}

/** 当前 order 派生：agent_order 非空 = 配置驱动模式；空/undefined = 默认模板拓扑（仅显示） */
function deriveOrder(config: ProjectConfig): string[][] {
  return config.agent_order && config.agent_order.length > 0
    ? config.agent_order
    : DEFAULT_AGENT_ORDER;
}

/** 角色所在层索引（不在 order 中 → 默认槽位，用于显示与移动边界判定） */
function slotOf(order: string[][], field: AgentField): number {
  const idx = order.findIndex((layer) => layer.includes(field));
  return idx >= 0 ? idx : DEFAULT_SLOTS[field];
}

export function AgentChainCard({ onConfigChange }: AgentChainCardProps = {}) {
  const { t } = useI18n();
  const config = useAgentStore((s) => s.config);
  const setConfig = useAgentStore((s) => s.setConfig);
  const providers = useModelsStore((s) => s.providers);

  // F42 #268（spec §5.2 Q3）：挂载即加载 provider-configs 数据源，Select 选项随 store 响应式更新
  useEffect(() => {
    void useModelsStore.getState().loadProviders();
  }, []);

  const chatOptions = selectChatModelOptions(providers);
  const followDefaultOption = { value: AGENT_DEFAULT_SENTINEL, label: t('ag.followDefault') };

  return (
    <section data-testid="agent-chain-card" className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('ag.chainTitle')}</h2>
      <p className="mt-1 text-[12px] text-ink-3">{t('ag.chainDesc')}</p>
      <div className="mt-4 divide-y divide-line">
        {AGENT_ROLES.map((role) => {
          const value = config[role.field];
          // 三态语义（#225）：null=关闭（禁用角色）；字符串=开启且指定模型；
          // "__default__"（AGENT_DEFAULT_SENTINEL）=跟随默认（预留）
          const checked = typeof value === 'string';
          const tagWarn =
            typeof value === 'string' &&
            value !== AGENT_DEFAULT_SENTINEL &&
            !chatOptions.some((o) => o.value === value);
          const tag =
            value == null
              ? t('ag.disabled')
              : value === AGENT_DEFAULT_SENTINEL
                ? t('ag.defaultModel')
                : tagWarn && !value.includes('/')
                  ? t('ag.modelFormatFix')
                  : tagWarn
                    ? t('ag.unregisteredModel')
                    : value;
          // F42 #269：槽位号 + 上移/下移边界（M6 契约）
          const order = deriveOrder(config);
          const slot = slotOf(order, role.field);
          const idx = order.findIndex((layer) => layer.includes(role.field));
          const upDisabled = idx <= 0; // 首层或不在 order → 上移禁用
          const downDisabled = idx < 0 || idx === order.length - 1; // 末层或不在 order → 下移禁用
          const moveRole = (direction: 'up' | 'down') => {
            // 上移 = 并入上一层（与该层角色并行）；下移 = 并入下一层；
            // 移动后空层压缩；操作作用于 config.agent_order（首次移动显式化默认拓扑）
            const base = deriveOrder(config).map((layer) => [...layer]);
            const current = base.findIndex((layer) => layer.includes(role.field));
            if (current < 0) return;
            const target = direction === 'up' ? current - 1 : current + 1;
            if (target < 0 || target >= base.length) return;
            const targetLayer = base[target]; // 目标层（field 不在其中）
            // 从原层移除角色；层变空 → 压缩删除
            base[current] = base[current].filter((r) => r !== role.field);
            const compressed = base.filter((layer) => layer.length > 0);
            // 目标层在压缩后的位置（filter 保留引用，内容定位）
            const targetIdx = compressed.findIndex((layer) => layer === targetLayer);
            if (targetIdx >= 0) {
              // 并入目标层末尾（保持层内既有角色）
              compressed[targetIdx].push(role.field);
            } else {
              // 目标层为空槽（[]）→ 按压缩后位置插入新层
              const before = base
                .slice(0, target)
                .filter((layer) => layer.length > 0).length;
              compressed.splice(before, 0, [role.field]);
            }
            setConfig({ agent_order: compressed });
            onConfigChange?.();
          };
          const toggle = () => {
            // 关闭 → 显式 null（JSON.stringify 保留 → 后端落库 null → 重启仍关闭）；
            // 配置驱动模式（order 非空）同步从 agent_order 剔除该角色并压缩空层（B1）；
            // 打开 → sentinel "__default__"（跟随默认，本期无模型选择 UI）；
            // 配置驱动模式同步加入默认槽位；默认模板模式（order 空）不写 agent_order
            const patch = agentPatch(role.field, checked ? null : AGENT_DEFAULT_SENTINEL);
            if (checked) {
              // 关闭
              if (config.agent_order && config.agent_order.length > 0) {
                const removed = config.agent_order
                  .map((layer) => layer.filter((r) => r !== role.field))
                  .filter((layer) => layer.length > 0);
                setConfig({ ...patch, agent_order: removed });
              } else {
                setConfig(patch);
              }
            } else if (config.agent_order && config.agent_order.length > 0) {
              // 开启（配置驱动模式）：角色加入默认槽位（新层插入，既有层后移）
              const order = config.agent_order.map((layer) => [...layer]);
              order.splice(DEFAULT_SLOTS[role.field], 0, [role.field]);
              setConfig({ ...patch, agent_order: order });
            } else {
              // 开启（默认模板模式）：只写 field，不写 agent_order（B1 保持默认模式）
              setConfig(patch);
            }
            onConfigChange?.();
          };
          return (
            <div key={role.field} className="flex items-center gap-3 py-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-weak text-accent">
                <role.icon className="h-4 w-4" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium">{t(role.nameKey)}</span>
                  <span
                    className={`rounded bg-surface-3 px-1.5 py-0.5 text-[11px] ${tagWarn ? 'text-warn' : 'text-ink-3'}`}
                  >
                    {tag}
                  </span>
                </div>
                <p className="mt-0.5 text-[12px] text-ink-3">{t(role.descKey)}</p>
              </div>
              {/* F42 #269：槽位号 + 上移/下移（M6 契约，data-testid 即契约） */}
              <div className="flex shrink-0 items-center gap-1" aria-label={`${t('ag.slot')} ${slot}`}>
                <span
                  data-testid={`agent-order-slot-${role.field}`}
                  className="rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-ink-3"
                  aria-label={`${t('ag.slot')} ${slot}`}
                >
                  {slot}
                </span>
                <button
                  type="button"
                  data-testid={`agent-order-move-up-${role.field}`}
                  aria-label={t('ag.moveUp')}
                  disabled={upDisabled}
                  onClick={() => moveRole('up')}
                  className="flex h-6 w-6 items-center justify-center rounded border border-line text-ink-3 hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ↑
                </button>
                <button
                  type="button"
                  data-testid={`agent-order-move-down-${role.field}`}
                  aria-label={t('ag.moveDown')}
                  disabled={downDisabled}
                  onClick={() => moveRole('down')}
                  className="flex h-6 w-6 items-center justify-center rounded border border-line text-ink-3 hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ↓
                </button>
              </div>
              {checked && (
                <Select
                  value={typeof value === 'string' ? value : AGENT_DEFAULT_SENTINEL}
                  onValueChange={(v) => {
                    setConfig(agentPatch(role.field, v));
                    onConfigChange?.();
                  }}
                >
                  <SelectTrigger
                    data-testid={`agent-model-select-${role.field}`}
                    aria-label={t('ag.defaultModel')}
                    className="w-52"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={followDefaultOption.value}>{followDefaultOption.label}</SelectItem>
                    {chatOptions.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <Switch checked={checked} onCheckedChange={toggle} aria-label={t(role.nameKey)} />
            </div>
          );
        })}
      </div>
    </section>
  );
}
