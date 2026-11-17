import React from "react";
import { HammerMark } from "@/components/Logo";
import HfAuthChip from "./HfAuthChip";

const LandingTopBar: React.FC = () => {
  return (
    <header className="sticky top-0 z-30 w-full border-b border-sky-200/60 bg-sky-100/60 backdrop-blur-xl supports-[backdrop-filter]:bg-sky-100/45">
      <div className="mx-auto flex h-12 max-w-[1680px] items-center justify-between px-4">
        <div className="flex items-center gap-2">
          <HammerMark className="h-8 w-8" />
          <span className="text-lg font-semibold tracking-tight text-slate-900">
            LeForge
          </span>
        </div>
        <HfAuthChip />
      </div>
    </header>
  );
};

export default LandingTopBar;
