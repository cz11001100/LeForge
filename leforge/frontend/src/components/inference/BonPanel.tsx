import React, { useEffect, useState } from "react";
import { Loader2, RefreshCw, SquarePen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { NumberInput } from "@/components/ui/number-input";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useApi } from "@/contexts/ApiContext";
import { useToast } from "@/hooks/use-toast";
import { JobRecord, listJobs } from "@/lib/jobsApi";
import {
  BonCandidateRow,
  BonMode,
  BonRetrainStatus,
  InferenceStatus,
  getBonCandidates,
  getBonRetrainStatus,
  startBonRetrain,
  updateBonConfig,
} from "@/lib/inferenceApi";

interface Props {
  status: InferenceStatus;
  drawing: boolean;
  canDraw: boolean;
  onToggleDraw: () => void;
}

const ScoreBars: React.FC<{ scores: number[]; selected: number }> = ({
  scores,
  selected,
}) => {
  if (scores.length === 0) return <span className="text-slate-500">暂无候选</span>;
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const span = max - min || 1;
  return (
    <span className="inline-flex items-end gap-px h-6" title="候选分数（越高越好），绿色为选中">
      {scores.map((s, i) => (
        <span
          key={i}
          title={`#${i} ${s.toFixed(1)}`}
          className={`w-1.5 rounded-sm ${i === selected ? "bg-green-500" : "bg-slate-300"}`}
          style={{ height: `${4 + (20 * (s - min)) / span}px` }}
        />
      ))}
    </span>
  );
};

const CandidateLogDialog: React.FC<{
  open: boolean;
  onOpenChange: (v: boolean) => void;
  repoId: string;
}> = ({ open, onOpenChange, repoId }) => {
  const { baseUrl, fetchWithHeaders } = useApi();
  const [rows, setRows] = useState<BonCandidateRow[]>([]);
  const [total, setTotal] = useState(0);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    getBonCandidates(baseUrl, fetchWithHeaders, repoId, 50)
      .then((res) => {
        setRows(res.rows ?? []);
        setTotal(res.total ?? res.rows?.length ?? 0);
        setPath(res.path ?? "");
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    if (open) load();
  }, [open, repoId]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-sky-50 border-sky-200 text-slate-900 sm:max-w-[720px] max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-slate-900">BoN 候选日志</DialogTitle>
        </DialogHeader>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span>共 {total} 条重规划 · 显示最近 {rows.length} 条</span>
          <Button
            variant="outline"
            size="sm"
            onClick={load}
            disabled={loading}
            className="ml-auto bg-sky-50 border-sky-200 text-slate-700 hover:bg-sky-50"
          >
            {loading ? (
              <Loader2 className="w-3 h-3 mr-1 animate-spin" />
            ) : (
              <RefreshCw className="w-3 h-3 mr-1" />
            )}
            刷新
          </Button>
        </div>
        <p className="text-[10px] text-slate-500 break-all">{path}</p>
        {rows.length === 0 ? (
          <p className="text-sm text-slate-500 py-6 text-center">
            暂无候选记录（BoN 未启用或尚未重规划）。
          </p>
        ) : (
          <table className="w-full text-xs text-slate-700">
            <thead>
              <tr className="text-left text-slate-500 border-b border-sky-200">
                <th className="py-1 pr-2">tick</th>
                <th className="py-1 pr-2">选中</th>
                <th className="py-1 pr-2">分数（N 个候选）</th>
                <th className="py-1 pr-2">σ×</th>
                <th className="py-1">N</th>
              </tr>
            </thead>
            <tbody>
              {[...rows].reverse().map((r) => (
                <tr key={r.tick} className="border-b border-sky-100">
                  <td className="py-1 pr-2 font-mono">{r.tick}</td>
                  <td className="py-1 pr-2 font-mono text-green-600">#{r.selected_id}</td>
                  <td className="py-1 pr-2 font-mono">
                    {r.scores.map((s, i) => (
                      <span key={i} className={i === r.selected_id ? "text-green-600" : ""}>
                        {s.toFixed(1)}
                        {i < r.scores.length - 1 ? " " : ""}
                      </span>
                    ))}
                  </td>
                  <td className="py-1 pr-2 font-mono">{r.sigma_scale}</td>
                  <td className="py-1 font-mono">{r.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </DialogContent>
    </Dialog>
  );
};

const RetrainDialog: React.FC<{
  open: boolean;
  onOpenChange: (v: boolean) => void;
  captureRepo: string;
}> = ({ open, onOpenChange, captureRepo }) => {
  const { baseUrl, fetchWithHeaders } = useApi();
  const { toast } = useToast();
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [jobId, setJobId] = useState("");
  const [target, setTarget] = useState("");
  const [status, setStatus] = useState<BonRetrainStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    listJobs(baseUrl, fetchWithHeaders, 50)
      .then((list) => {
        const usable = list.filter(
          (j) => (j.runner === "local" || j.runner === "ssh") && j.checkpoint_count > 0,
        );
        setJobs(usable);
        setJobId((prev) => prev || usable[0]?.id || "");
      })
      .catch(() => setJobs([]));
    getBonRetrainStatus(baseUrl, fetchWithHeaders)
      .then((s) => setStatus(s))
      .catch(() => setStatus(null));
  }, [open, baseUrl, fetchWithHeaders]);

  const running = status?.phase === "merging" || status?.phase === "starting";
  useEffect(() => {
    if (!open || !running) return;
    const id = setInterval(() => {
      getBonRetrainStatus(baseUrl, fetchWithHeaders)
        .then((s) => {
          setStatus(s);
          if (s.phase === "done") {
            toast({ title: "回灌续训已启动", description: `新任务 ${s.job_id}，合并集 ${s.target}` });
          }
          if (s.phase === "error") {
            toast({ title: "回灌续训失败", description: s.message, variant: "destructive" });
          }
        })
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(id);
  }, [open, running, baseUrl, fetchWithHeaders, toast]);

  const selected = jobs.find((j) => j.id === jobId);
  const start = () => {
    if (!jobId || !captureRepo) return;
    setBusy(true);
    startBonRetrain(baseUrl, fetchWithHeaders, {
      job_id: jobId,
      capture_repo: captureRepo,
      target_repo_id: target.trim() || undefined,
    })
      .then((res) => {
        setStatus({ phase: "merging", target: res.target_repo_id, labeled: res.labeled });
        toast({ title: "回灌开始", description: res.message });
      })
      .catch((e) =>
        toast({
          title: "回灌没启动",
          description: e instanceof Error ? e.message : String(e),
          variant: "destructive",
        }),
      )
      .finally(() => setBusy(false));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-sky-50 border-sky-200 text-slate-900 sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="text-slate-900">回灌续训（数据飞轮）</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm text-slate-700">
          <p className="text-xs text-slate-500">
            把本集采集集（含自动判成标签）合并进源任务的训练集，再从源任务 checkpoint
            续训。合并在后台跑，完成后自动开训。
          </p>
          <div className="space-y-1">
            <span className="text-xs text-slate-500">采集数据集</span>
            <p className="font-mono text-xs break-all">{captureRepo || "（本次运行未录数据）"}</p>
          </div>
          <div className="space-y-1">
            <span className="text-xs text-slate-500">源训练任务</span>
            <Select value={jobId} onValueChange={setJobId} disabled={running || busy}>
              <SelectTrigger className="bg-sky-50 border-sky-200 text-slate-900 text-xs">
                <SelectValue placeholder="选择要续训的任务" />
              </SelectTrigger>
              <SelectContent className="bg-sky-50 border-sky-200 text-slate-900">
                {jobs.map((j) => (
                  <SelectItem key={j.id} value={j.id}>
                    {j.name} · {j.runner}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selected && (
              <p className="text-[10px] text-slate-500 break-all">
                训练集：{selected.config.dataset_repo_id}
              </p>
            )}
          </div>
          <div className="space-y-1">
            <span className="text-xs text-slate-500">合并集名字（留空自动起）</span>
            <Input
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="user/xxx_flywheel_1114_1200"
              disabled={running || busy}
              className="bg-sky-50 border-sky-200 text-slate-900 text-xs"
            />
          </div>
          {status && status.phase !== "idle" && (
            <p
              className={`text-xs ${
                status.phase === "error"
                  ? "text-red-600"
                  : status.phase === "done"
                    ? "text-green-600"
                    : "text-amber-600"
              }`}
            >
              {status.phase === "merging" && `合并中 → ${status.target}（已写标签 ${status.labeled ?? 0} 集）`}
              {status.phase === "starting" && "合并完成，正在启动续训…"}
              {status.phase === "done" && `续训已启动：${status.job_id}`}
              {status.phase === "error" && status.message}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
              className="bg-sky-50 border-sky-200 text-slate-700 hover:bg-sky-50"
            >
              关闭
            </Button>
            <Button
              onClick={start}
              disabled={!jobId || !captureRepo || busy || running}
              className="bg-green-600 hover:bg-green-500 text-white"
            >
              {busy || running ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : null}
              开始回灌续训
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

const BonPanel: React.FC<Props> = ({ status, drawing, canDraw, onToggleDraw }) => {
  const { baseUrl, fetchWithHeaders } = useApi();
  const { toast } = useToast();
  const bon = status.bon ?? {};
  // The subprocess only publishes state when it was started with BoN.
  const live = bon.enabled !== undefined;
  const enabled = !!bon.enabled;

  const [n, setN] = useState(8);
  const [sigma, setSigma] = useState(0.15);
  const [k, setK] = useState(15);
  const [confirmK, setConfirmK] = useState(10);
  const [mode, setMode] = useState<BonMode>("bon");
  const [logOpen, setLogOpen] = useState(false);
  const [retrainOpen, setRetrainOpen] = useState(false);

  useEffect(() => {
    if (!live) return;
    setN(bon.n ?? 8);
    setSigma(bon.sigma_scale ?? 0.15);
    setK(bon.k ?? 15);
    setConfirmK(bon.confirm_k ?? 10);
    setMode((bon.mode as BonMode) ?? "bon");
  }, [live]);

  const push = (cfg: Record<string, unknown>) => {
    updateBonConfig(baseUrl, fetchWithHeaders, cfg).catch((e) =>
      toast({
        title: "BoN 配置没送达",
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      }),
    );
  };

  const repoId = status.takeover?.repo_id ?? status.dataset_repo_id ?? "";
  const captureRepoAvailable = !!repoId;
  const inputCls = "w-16 h-7 bg-sky-50 border-sky-200 text-slate-900 text-xs";

  return (
    <div className="flex-shrink-0 mb-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-700">
      <span className="font-semibold text-slate-900">BoN 飞轮</span>
      <Switch
        checked={enabled}
        disabled={!live}
        onCheckedChange={(v) => push({ enabled: v })}
      />
      {!live ? (
        <span className="text-slate-500">本次启动未带 BoN，控件仅查看</span>
      ) : (
        <>
          <label className="flex items-center gap-1">
            模式
            <Select
              value={mode}
              onValueChange={(v) => {
                setMode(v as BonMode);
                push({ mode: v });
              }}
              disabled={!enabled}
            >
              <SelectTrigger className="h-7 w-24 bg-sky-50 border-sky-200 text-slate-900 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-sky-50 border-sky-200 text-slate-900">
                <SelectItem value="bon">BoN</SelectItem>
                <SelectItem value="greedy">greedy</SelectItem>
                <SelectItem value="alternate">alternate 对照</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label className="flex items-center gap-1">
            N
            <NumberInput
              min={1}
              max={32}
              value={n}
              disabled={!enabled}
              onChange={(v) => {
                if (v === undefined) return;
                setN(v);
                push({ n: v });
              }}
              className={inputCls}
            />
          </label>
          <label className="flex items-center gap-1">
            k
            <NumberInput
              min={1}
              max={100}
              value={k}
              disabled={!enabled}
              onChange={(v) => {
                if (v === undefined) return;
                setK(v);
                push({ k: v });
              }}
              className={inputCls}
            />
          </label>
          <label className="flex items-center gap-1">
            σ×
            <NumberInput
              integer={false}
              min={0.05}
              max={0.5}
              step={0.05}
              value={sigma}
              disabled={!enabled}
              onChange={(v) => {
                if (v === undefined) return;
                setSigma(v);
                push({ sigma_scale: v });
              }}
              className={inputCls}
            />
          </label>
          <label className="flex items-center gap-1">
            K
            <NumberInput
              min={1}
              max={60}
              value={confirmK}
              disabled={!enabled}
              onChange={(v) => {
                if (v === undefined) return;
                setConfirmK(v);
                push({ confirm_k: v });
              }}
              className={inputCls}
            />
          </label>
          <span
            className={bon.verifier_ok ? "text-green-600" : "text-amber-600"}
            title="aim verifier  held-out R²，低于 0.5 自动退回 greedy"
          >
            verifier R²={bon.verifier_r2 != null ? bon.verifier_r2.toFixed(2) : "—"}
            {bon.verifier_ok ? "" : "（不可用→greedy）"}
          </span>
          <span className={bon.judge_success ? "text-green-600" : "text-slate-500"}>
            本集{bon.judge_success ? "已判成" : "未判成"} · 成 {bon.success_count ?? 0} / 败{" "}
            {bon.fail_count ?? 0}
          </span>
          {bon.active_mode && (
            <span className="text-slate-500">
              本集臂{" "}
              <span className={bon.active_mode === "bon" ? "text-green-600" : "text-slate-900"}>
                {bon.active_mode}
              </span>
              {bon.episode_index != null ? ` · ep ${bon.episode_index}` : ""}
            </span>
          )}
          {bon.arm_stats && (
            <span className="text-slate-500" title="对照实验：每臂 成/败">
              greedy {bon.arm_stats.greedy?.[0] ?? 0}/{bon.arm_stats.greedy?.[1] ?? 0} · BoN{" "}
              {bon.arm_stats.bon?.[0] ?? 0}/{bon.arm_stats.bon?.[1] ?? 0}
            </span>
          )}
          <ScoreBars scores={bon.last_scores ?? []} selected={bon.last_selected ?? -1} />
        </>
      )}
      <span className="ml-auto flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onToggleDraw}
          disabled={!canDraw}
          className={`h-7 border-sky-200 text-xs ${
            drawing
              ? "bg-amber-100 border-amber-400 text-amber-700"
              : "bg-sky-50 text-slate-700 hover:bg-sky-50"
          }`}
          title={`在 ${bon.camera ?? "up"} 画面上拖拽绘制目标框`}
        >
          <SquarePen className="w-3 h-3 mr-1" />
          {drawing ? "绘制中…" : "画目标框"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setRetrainOpen(true)}
          disabled={!captureRepoAvailable}
          className="h-7 bg-sky-50 border-sky-200 text-slate-700 hover:bg-sky-50 text-xs"
          title="把采集集合并进训练集并续训"
        >
          回灌续训
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setLogOpen(true)}
          className="h-7 bg-sky-50 border-sky-200 text-slate-700 hover:bg-sky-50 text-xs"
        >
          候选日志
        </Button>
      </span>
      <CandidateLogDialog open={logOpen} onOpenChange={setLogOpen} repoId={repoId} />
      <RetrainDialog open={retrainOpen} onOpenChange={setRetrainOpen} captureRepo={repoId} />
    </div>
  );
};

export default BonPanel;
