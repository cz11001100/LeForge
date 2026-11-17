import React, { useState } from "react";
import { Check, Copy, RefreshCw, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import DialogHeading from "@/components/ui/DialogHeading";
import { useHfAuth } from "@/contexts/HfAuthContext";

interface HfAuthDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const HfAuthDialog: React.FC<HfAuthDialogProps> = ({ open, onOpenChange }) => {
  const { auth, refetch } = useHfAuth();
  const [copied, setCopied] = useState(false);
  const [refetching, setRefetching] = useState(false);

  if (auth.status !== "unauthenticated") {
    return null;
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(auth.loginCommand);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.warn("Clipboard write failed:", err);
    }
  };

  const handleRefetch = async () => {
    setRefetching(true);
    try {
      await refetch();
    } finally {
      setRefetching(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex w-[calc(100%-1.5rem)] flex-col gap-0 overflow-hidden border-sky-200 bg-sky-100 p-0 text-slate-900 sm:max-w-[560px]">
        <DialogHeading
          icon={<AlertTriangle className="h-4 w-4 text-amber-600" />}
          iconClassName="bg-amber-100"
          title="Hugging Face CLI 未配置"
          description="上传、训练、Hub 回放都需要已登录的 HF CLI。在终端运行："
        />
      <div className="px-6 py-5">
        <pre className="bg-sky-50 p-3 rounded border border-sky-300 text-xs sm:text-sm overflow-x-auto flex items-center justify-between gap-2">
          <code className="text-green-700">{auth.loginCommand}</code>
          <button
            type="button"
            onClick={handleCopy}
            className="flex-shrink-0 text-slate-600 hover:text-slate-800 transition-colors"
            aria-label="Copy command"
          >
            {copied ? (
              <Check className="w-4 h-4 text-green-700" />
            ) : (
              <Copy className="w-4 h-4" />
            )}
          </button>
        </pre>
      </div>
      <div className="flex justify-end border-t border-sky-200/70 bg-sky-100/60 px-6 py-3">
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefetch}
          disabled={refetching}
          className="border-amber-600/40 bg-transparent text-amber-700 hover:bg-amber-100 hover:text-amber-700"
        >
          <RefreshCw
            className={`w-4 h-4 mr-2 ${refetching ? "animate-spin" : ""}`}
          />
          我已登录 — 重新检测
        </Button>
      </div>
    </DialogContent>
    </Dialog>
  );
};

export default HfAuthDialog;
