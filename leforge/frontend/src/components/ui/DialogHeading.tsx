import React from "react";
import {
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface DialogHeadingProps {
  icon: React.ReactNode;
  iconClassName?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
}

/** Compact left-aligned dialog header: tinted mark, title, one-line hint. */
const DialogHeading: React.FC<DialogHeadingProps> = ({
  icon,
  iconClassName,
  title,
  description,
}) => (
  <DialogHeader className="shrink-0 border-b border-sky-200/70 pr-8 text-left">
    <div className="flex items-center gap-3">
      <span
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
          iconClassName,
        )}
      >
        {icon}
      </span>
      <div className="min-w-0">
        <DialogTitle className="text-left text-xl font-bold">{title}</DialogTitle>
        {description ? (
          <DialogDescription className="text-left text-sm text-slate-600">
            {description}
          </DialogDescription>
        ) : null}
      </div>
    </div>
  </DialogHeader>
);

export default DialogHeading;