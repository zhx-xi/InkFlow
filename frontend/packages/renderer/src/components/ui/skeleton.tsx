/** 骨架屏（spec §6.2①：项目列表/章节树加载态） */
import { cn } from '../../lib/cn';

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded bg-surface-3', className)} />;
}
