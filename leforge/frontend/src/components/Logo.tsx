import React from 'react';
import { cn } from '@/lib/utils';

interface LogoProps extends React.HTMLAttributes<HTMLDivElement> {
  iconOnly?: boolean;
}

/** LeForge mark: a hammer struck inside a forged hex nut. */
export const HammerMark: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox="0 0 40 40"
    className={cn('h-8 w-8 shrink-0', className)}
    role="img"
    aria-label="LeForge"
  >
    <path d="M12 3h16l10 17-10 17H12L2 20Z" fill="#0A4A72" />
    <path d="M13.6 6.2h12.8l8 13.8-8 13.8H13.6l-8-13.8Z" fill="#0E6396" />
    <g transform="rotate(-40 20 20)">
      <rect x="11.8" y="9.8" width="16.4" height="6.4" rx="2.4" fill="#EAF7FF" />
      <rect x="11.8" y="9.8" width="3.4" height="6.4" rx="1.7" fill="#9FD6F4" />
      <rect x="17.6" y="15.4" width="4.8" height="15" rx="2.4" fill="#CFEEFD" />
    </g>
    </svg>
);

const Logo: React.FC<LogoProps> = ({ className, iconOnly = false }) => {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <HammerMark />
      {!iconOnly && (
        <span className="text-2xl font-bold tracking-tight text-slate-900">LeForge</span>
      )}
    </div>
  );
};

export default Logo;