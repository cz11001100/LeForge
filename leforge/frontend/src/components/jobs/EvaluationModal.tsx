import React, { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FlaskConical } from "lucide-react";
import { JobRecord } from "@/lib/jobsApi";
import EvaluationCard from "@/components/jobs/EvaluationCard";
import SimEvalCard from "@/components/jobs/SimEvalCard";
import { modelStepOf, modelBaseName, ModelVariant } from "@/lib/modelGroups";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  job: JobRecord | null;
  // Sibling checkpoints of one imported run; when given, the card shows a
  // checkpoint selector (in its parameter grid) that switches the evaluated job.
  group?: JobRecord[];
}

const EvaluationModal: React.FC<Props> = ({ open, onOpenChange, job, group }) => {
  const members = group && group.length > 0 ? group : null;
  const [activeId, setActiveId] = useState<string | null>(job?.id ?? null);
  useEffect(() => {
    setActiveId(job?.id ?? null);
  }, [job?.id]);
  const activeJob = members
    ? members.find((m) => m.id === activeId) ?? members[0]
    : job;
  const title = activeJob
    ? members
      ? modelBaseName(activeJob.name)
      : activeJob.name
    : "";
  const variants: ModelVariant[] | undefined = members
    ? members.map((m) => ({ step: modelStepOf(m.name), jobId: m.id }))
    : undefined;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex w-[calc(100%-1.5rem)] max-h-[90vh] flex-col gap-0 overflow-hidden border-sky-200 bg-sky-100/85 p-0 text-slate-900 sm:max-w-[1200px]">
        <DialogHeader className="shrink-0 border-b border-sky-200 px-6 py-4">
          <div className="flex items-center gap-3 pr-8 text-left">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-purple-100">
              <FlaskConical className="h-4 w-4 text-purple-700" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="text-left text-xl font-bold">
                模型评测 Model Evaluation{title ? ` · ${title}` : ""}
              </DialogTitle>
              <DialogDescription className="text-left text-sm text-slate-600">
                查看真机评测与仿真评测结果。
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>
        {activeJob ? (
          <div className="flex-1 overflow-y-auto px-6 py-5">
            <div className="grid gap-4 xl:grid-cols-2 xl:items-start">
              <EvaluationCard
                key={activeJob.id}
                job={activeJob}
                variants={variants}
                onSelectJob={setActiveId}
              />
              <SimEvalCard
                key={`sim-${activeJob.id}`}
                job={activeJob}
                variants={variants}
                onSelectJob={setActiveId}
              />
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
};

export default EvaluationModal;
