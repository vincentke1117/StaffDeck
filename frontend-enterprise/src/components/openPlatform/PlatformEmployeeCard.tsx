import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import IconArrowRight from '../../assets/icons/arrow-right.svg?react';

export type PlatformStat = {
  value: ReactNode;
  label: string;
};

export type PlatformEmployeeCardProps = {
  /** Avatar illustration, typically an <EmployeeAvatar />. */
  avatar: ReactNode;
  name: ReactNode;
  role: ReactNode;
  online?: boolean;
  description: ReactNode;
  /** Bottom metric segments (资料 / 技能 / SOP …). */
  stats: PlatformStat[];
  onOpen?: () => void;
  className?: string;
};

/**
 * Compact 数字员工广场 card. Mirrors the Figma layout: a grey banner holding the
 * avatar (which pokes above the banner), name / role / online chip and a
 * chevron affordance, followed by a two-line description and a joined stat row.
 */
export default function PlatformEmployeeCard({
  avatar,
  name,
  role,
  online = true,
  description,
  stats,
  onOpen,
  className,
}: PlatformEmployeeCardProps) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        'group relative flex h-[140px] w-full shrink-0 flex-col justify-end gap-[6px] rounded-[20px] border-[0.5px] border-[#f6f6f6] bg-white p-[4px] text-left transition-shadow hover:shadow-[0_10px_24px_rgba(0,0,0,0.06)]',
        '',
        className,
      )}
    >
      <div className="flex w-full flex-col px-[6px] pb-[2px]">
        <div className="flex h-[54px] w-full items-end justify-between rounded-[14px] bg-[#f6f6f6] px-[8px] pb-[4px] pt-[8px]">
          <div className="flex min-w-0 items-end gap-[10px]">
            <div className="flex h-[59px] w-[50px] shrink-0 items-end justify-center">
              {avatar}
            </div>
            <div className="flex min-w-0 flex-col items-start justify-center gap-[2px]">
              <p className="truncate text-[10px] font-medium text-[#18181a] leading-[1.35]">{name}</p>
              <p className="truncate text-[8px] text-[#757f9c] leading-[1.6]">{role}</p>
              <span className="inline-flex w-[34px] items-center justify-center rounded-[90px] bg-white px-[4px] py-[2px]">
                <span className="flex items-center gap-[2px]">
                  <i
                    className={cn('size-[4px] shrink-0 rounded-full', online ? 'bg-[#22c55e]' : 'bg-[#9ca3af]')}
                    aria-hidden="true"
                  />
                  <span className="text-[8px] text-[#757f9c]">{online ? '在线' : '下线'}</span>
                </span>
              </span>
            </div>
          </div>
          <span className="grid size-[24px] shrink-0 self-center place-items-center rounded-[10px] bg-white text-[#757f9c] transition-colors group-hover:text-[#18181a]">
            <IconArrowRight className="size-[14px]" />
          </span>
        </div>
      </div>

      <p className="line-clamp-2 h-[26px] w-full px-[8px] text-[10px] leading-[13px] text-[#757f9c]">
        {description}
      </p>

      <div className="flex w-full items-stretch px-[8px] pb-[4px]">
        {stats.map((stat, index) => (
          <div
            key={stat.label}
            className={cn(
              'flex h-[28px] flex-1 items-center justify-center border-[0.5px] border-[#e3e7f1] px-[10px]',
              index === 0 && 'rounded-l-[10px]',
              index === stats.length - 1 && 'rounded-r-[10px]',
              index > 0 && 'border-l-0',
            )}
          >
            <span className="flex items-baseline gap-[2px] leading-none">
              <span className="text-[10px] font-medium text-[#18181a]">{stat.value}</span>
              <span className="text-[8px] text-[#464c5e]">{stat.label}</span>
            </span>
          </div>
        ))}
      </div>
    </button>
  );
}
