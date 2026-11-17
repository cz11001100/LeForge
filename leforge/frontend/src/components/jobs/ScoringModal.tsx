import React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Gauge } from "lucide-react";
import RolloutScoreCard from "@/components/jobs/RolloutScoreCard";

/**
 * Scoring from a dataset card. The full section also lives on the Dataset page;
 * this is the short path — jump straight to the dataset you are looking at
 * without leaving the job list.
 */
const ScoringModal: React.FC<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  datasetRepoId?: string;
}> = ({ open, onOpenChange, datasetRepoId }) => {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex w-[calc(100%-1.5rem)] max-h-[90vh] flex-col gap-0 overflow-hidden border-sky-200 bg-sky-100/85 p-0 text-slate-900 sm:max-w-[1280px]">
        <DialogHeader className="shrink-0 border-b border-sky-200 px-6 py-4">
          <div className="flex items-center gap-3 pr-8 text-left">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-100">
              <Gauge className="h-4 w-4 text-indigo-700" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="text-left text-xl font-bold">
                RA-BC{datasetRepoId ? ` · ${datasetRepoId}` : ""}
              </DialogTitle>
              <DialogDescription className="text-left text-sm text-slate-600">
                查看打分进度、成功率与接管率。
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <RolloutScoreCard initialRepoId={datasetRepoId ?? ""} />
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ScoringModal;