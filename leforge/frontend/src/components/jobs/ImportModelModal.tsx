import React, { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import DialogHeading from "@/components/ui/DialogHeading";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertTriangle, CheckCircle2, Download, Loader2 } from "lucide-react";
import { useApi } from "@/contexts/ApiContext";
import { importModel } from "@/lib/jobsApi";
import { useToast } from "@/hooks/use-toast";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: () => void;
}

const ImportModelModal: React.FC<Props> = ({ open, onOpenChange, onImported }) => {
  const { baseUrl, fetchWithHeaders } = useApi();
  const { toast } = useToast();
  const [source, setSource] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [importedLabel, setImportedLabel] = useState<string | null>(null);

  // The import is one blocking request (a Hub repo needs a networked listing),
  // so the honest progress signal is an indeterminate bar plus elapsed time.
  useEffect(() => {
    if (!submitting) return;
    const started = Date.now();
    setElapsed(0);
    const timer = window.setInterval(
      () => setElapsed(Math.round((Date.now() - started) / 1000)),
      500,
    );
    return () => window.clearInterval(timer);
  }, [submitting]);

  useEffect(() => {
    if (!open) {
      setError(null);
      setImportedLabel(null);
    }
  }, [open]);

  const handleSubmit = async () => {
    const src = source.trim();
    if (!src) return;
    setSubmitting(true);
    setError(null);
    setImportedLabel(null);
    try {
      const record = await importModel(
        baseUrl,
        fetchWithHeaders,
        src,
        name.trim() || undefined,
      );
      const label = record?.name || name.trim() || src;
      setImportedLabel(label);
      toast({ title: "已导入模型", description: label });
      setSource("");
      setName("");
      onImported();
      // Let the green confirmation render before the dialog disappears.
      window.setTimeout(() => onOpenChange(false), 1200);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
      toast({ title: "导入失败", description: message, variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!submitting) onOpenChange(next);
      }}
    >
      <DialogContent className="flex w-[calc(100%-1.5rem)] flex-col gap-0 overflow-hidden border-sky-200 bg-sky-100 p-0 text-slate-900 sm:max-w-[560px]">
        <DialogHeading
          icon={<Download className="h-4 w-4 text-blue-600" />}
          iconClassName="bg-blue-100"
          title="导入模型 Import a model"
          description="指向本地目录或 Hub 仓库，导入后即可推理。"
        />

        <div className="space-y-4 px-6 py-5">
          <div className="space-y-2">
            <Label htmlFor="source" className="text-sm font-medium text-slate-700">
              Local path or Hugging Face repo id
            </Label>
            <Input
              id="source"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder="/path/to/pretrained_model  or  user/my-policy"
              disabled={submitting}
              className="bg-sky-50 border-sky-300 text-slate-900"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSubmit();
              }}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="name" className="text-sm font-medium text-slate-700">
              Display name (optional)
            </Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My imported policy"
              disabled={submitting}
              className="bg-sky-50 border-sky-300 text-slate-900"
            />
          </div>

          {submitting ? (
            <div className="space-y-2 rounded-lg border border-sky-300 bg-sky-50/70 p-3">
              <div className="flex items-center justify-between gap-2 text-xs text-slate-700">
                <span className="flex items-center gap-2 min-w-0">
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-700" />
                  <span className="truncate">
                    {source.includes("/") && !source.startsWith("/")
                      ? "正在从 Hugging Face 读取模型信息（需联网，可能几十秒）…"
                      : "正在校验本地模型目录…"}
                  </span>
                </span>
                <span className="tabular-nums shrink-0 text-blue-700">{elapsed}s</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-sky-200">
                <div className="h-1.5 w-full rounded-full bg-blue-100 animate-pulse" />
              </div>
            </div>
          ) : null}

          {error ? (
            <Alert className="bg-red-100 border-red-300 text-red-700">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription className="break-all">{error}</AlertDescription>
            </Alert>
          ) : null}

          {importedLabel ? (
            <Alert className="bg-green-100 border-green-300 text-green-700">
              <CheckCircle2 className="h-4 w-4" />
              <AlertDescription>已导入：{importedLabel}</AlertDescription>
            </Alert>
          ) : null}

          </div>

        <div className="flex flex-col-reverse gap-3 border-t border-sky-200/70 bg-sky-100/60 px-6 py-3 sm:flex-row sm:justify-end">
          <Button
            onClick={() => onOpenChange(false)}
            disabled={submitting}
            variant="outline"
            className="border-sky-400 text-slate-600 hover:bg-sky-200 hover:text-slate-900"
          >
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!source.trim() || submitting}
            className="bg-green-600 px-6 text-white hover:bg-green-700 disabled:opacity-40"
          >
            {submitting ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Download className="w-4 h-4 mr-2" />
            )}
            {submitting ? "Importing…" : "Import"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ImportModelModal;
