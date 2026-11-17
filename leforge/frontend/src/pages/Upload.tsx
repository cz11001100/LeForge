import React, { useState } from "react";
import { useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  ArrowLeft,
  ArrowLeftRight,
  ChevronDown,
  ChevronUp,
  Gauge,
  ListVideo,
  Search,
  ShieldCheck,
  Upload as UploadIcon,
  Database,
  ExternalLink,
  CheckCircle,
  Loader2,
  Trash2,
  Wrench,
} from "lucide-react";
import { useApi } from "@/contexts/ApiContext";
import {
  DatasetSource,
  checkDatasetHealth,
  startDatasetRepair,
} from "@/lib/replayApi";
import type { DatasetHealth, RepairProgress } from "@/lib/replayApi";
import Logo from "@/components/Logo";
import DatasetHealthWarning from "@/components/DatasetHealthWarning";
import DatasetSummaryCard from "@/components/DatasetSummaryCard";
import { compareRolloutProgress } from "@/lib/rolloutEvalApi";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface DatasetInfo {
  dataset_repo_id: string;
  tasks: { task: string; episodes: number }[];
  num_episodes: number;
  saved_episodes?: number;
  fps?: number;
  robot_type?: string;
  source?: DatasetSource;
  episodes?: { index: number; length: number }[];
}

import MergeSection from "@/components/dataset/MergeSection";
import DatasetTransferSection from "@/components/dataset/DatasetTransferSection";
import RolloutScoreCard from "@/components/jobs/RolloutScoreCard";
import SarmTrainCard from "@/components/jobs/SarmTrainCard";
import DatasetViewer from "@/components/datasets/DatasetViewer";

type TabKey = "episodes" | "quality" | "scoring" | "tools";

const DETAIL_TABS: {
  key: TabKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  { key: "episodes", label: "分集", icon: ListVideo },
  { key: "quality", label: "质量", icon: ShieldCheck },
  { key: "scoring", label: "RA-BC", icon: Gauge },
  { key: "tools", label: "工具", icon: Wrench },
];

const TOOL_TABS = DETAIL_TABS.filter((t) => t.key === "scoring" || t.key === "tools");

const TabBar: React.FC<{
  value: TabKey;
  onChange: (key: TabKey) => void;
  tabs: typeof DETAIL_TABS;
}> = ({ value, onChange, tabs }) => (
  <div className="mt-6 mb-4 flex flex-wrap items-center gap-1 border-b border-sky-300/60">
    {tabs.map(({ key, label, icon: Icon }) => (
      <button
        key={key}
        type="button"
        onClick={() => onChange(key)}
        aria-current={value === key ? "page" : undefined}
        className={`-mb-px flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
          value === key
            ? "border-sky-400 text-slate-900"
            : "border-transparent text-slate-600 hover:text-slate-800"
        }`}
      >
        <Icon className="h-4 w-4" />
        {label}
      </button>
    ))}
  </div>
);

const Stat: React.FC<{ label: string; value: string; sub?: string }> = ({
  label,
  value,
  sub,
}) => (
  <div className="min-w-0">
    <dt className="text-xs text-slate-600">{label}</dt>
    <dd className="mt-0.5 truncate text-sm font-semibold text-slate-900">
      {value}
      {sub ? (
        <span className="ml-1 text-xs font-normal text-slate-600">{sub}</span>
      ) : null}
    </dd>
  </div>
);

const Upload = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { baseUrl, fetchWithHeaders } = useApi();

  // Get initial dataset info from navigation state
  const initialDatasetInfo = location.state?.datasetInfo as DatasetInfo;
  // An "RA-BC" jump from a dataset card preselects it in the scoring section.
  const scoreRepoId = (location.state?.scoreRepoId as string | undefined) ?? "";

  // Tabs replace the old accordion stack; ?tab= keeps deep links working and a
  // RA-BC jump lands straight on the scoring panel.
  const [params, setParams] = useSearchParams();
  const rawTab = params.get("tab") as TabKey | null;
  const tab: TabKey =
    rawTab && DETAIL_TABS.some((t) => t.key === rawTab)
      ? rawTab
      : scoreRepoId
        ? "scoring"
        : "episodes";
  const setTab = (next: TabKey) => {
    const n = new URLSearchParams(params);
    n.set("tab", next);
    setParams(n, { replace: true });
  };

  const [episodeQuery, setEpisodeQuery] = useState("");
  const [episodeSort, setEpisodeSort] = useState<"index" | "length">("index");
  const [episodeAsc, setEpisodeAsc] = useState(true);

  // State for actual dataset info (will be loaded from backend)
  const [datasetInfo, setDatasetInfo] = useState<DatasetInfo | null>(null);
  const [isLoadingDatasetInfo, setIsLoadingDatasetInfo] = useState(true);

  const [isUploading, setIsUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState({
    phase: "",
    percent: 0,
    current: 0,
    total: 0,
  });
  const progressStream = React.useRef<EventSource | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [selectedEpisodes, setSelectedEpisodes] = useState<Set<number>>(
    new Set(),
  );
  const [showDeleteEpisodesConfirm, setShowDeleteEpisodesConfirm] =
    useState(false);
  const [isDeletingEpisode, setIsDeletingEpisode] = useState(false);

  // Dataset health check state
  const [health, setHealth] = useState<DatasetHealth | null>(null);  const [checkingHealth, setCheckingHealth] = useState(false);
  const [isRepairing, setIsRepairing] = useState(false);
  const [repairProgress, setRepairProgress] = useState<RepairProgress | null>(
    null,
  );

  // Which scorers already have a progress file for this dataset.
  const [scoredBackends, setScoredBackends] = useState<string[]>([]);
  const [viewerOpen, setViewerOpen] = useState(false);

  const loadDatasetInfo = React.useCallback(async () => {
    if (!initialDatasetInfo?.dataset_repo_id) {
      // Arrived without a dataset in hand (deep link, or just here to merge
      // datasets): render the page with the dataset-independent sections.
      setIsLoadingDatasetInfo(false);
      return;
    }

    try {
      const response = await fetchWithHeaders(`${baseUrl}/dataset-info`, {
        method: "POST",
        body: JSON.stringify({
          dataset_repo_id: initialDatasetInfo.dataset_repo_id,
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        setDatasetInfo({ ...data, saved_episodes: data.num_episodes });
      } else {
        setDatasetInfo(initialDatasetInfo);
      }
    } catch (error) {
      console.error("Error loading dataset info:", error);
      setDatasetInfo(initialDatasetInfo);
    } finally {
      setIsLoadingDatasetInfo(false);
    }
  }, [initialDatasetInfo, navigate, toast, baseUrl, fetchWithHeaders]);

  // Load actual dataset information from backend
  React.useEffect(() => {
    loadDatasetInfo();
  }, [loadDatasetInfo]);

  React.useEffect(() => {
    const repoId = datasetInfo?.dataset_repo_id;
    if (!repoId) {
      setScoredBackends([]);
      return;
    }
    let cancelled = false;
    compareRolloutProgress(baseUrl, fetchWithHeaders, repoId)
      .then((c) => {
        if (cancelled) return;
        // `available` means both parquets exist; otherwise the payload lists
        // whichever single backend has scored.
        setScoredBackends(c.available ? ["robometer", "sarm"] : c.backends ?? []);
      })
      .catch(() => {
        if (!cancelled) setScoredBackends([]);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetInfo?.dataset_repo_id, baseUrl, fetchWithHeaders]);

  const followUploadProgress = React.useCallback(() => {
    if (progressStream.current) return;
    const stream = new EventSource(`${baseUrl}/upload-progress`);
    stream.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setUploadProgress({
        phase: data.phase || "",
        percent: data.percent || 0,
        current: data.current || 0,
        total: data.total || 0,
      });
      if (data.completed) {
        setUploadSuccess(true);
        setUploadError(null);
        setIsUploading(false);
      } else if (data.error) {
        setUploadError(String(data.error));
        setIsUploading(false);
      }
      if (data.completed || data.error) {
        stream.close();
        progressStream.current = null;
      }
    };
    stream.onerror = () => {
      stream.close();
      progressStream.current = null;
    };
    progressStream.current = stream;
  }, [baseUrl]);

  React.useEffect(() => () => progressStream.current?.close(), []);

  // The upload runs on a server thread, so a refresh or a trip back home must not
  // pretend it stopped — re-attach to one that is still going.
  React.useEffect(() => {
    const repoId = initialDatasetInfo?.dataset_repo_id;
    if (!repoId) return;
    let cancelled = false;
    fetchWithHeaders(`${baseUrl}/upload-progress/current`)
      .then((r) => r.json())
      .then((p) => {
        if (cancelled || !p?.active || p.dataset_repo_id !== repoId) return;
        setIsUploading(true);
        setUploadProgress({
          phase: p.phase || "",
          percent: p.percent || 0,
          current: p.current || 0,
          total: p.total || 0,
        });
        followUploadProgress();
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [
    initialDatasetInfo?.dataset_repo_id,
    baseUrl,
    fetchWithHeaders,
    followUploadProgress,
  ]);

  // Check dataset health after loading info
  React.useEffect(() => {
    if (!datasetInfo?.dataset_repo_id) return;
    setCheckingHealth(true);
    checkDatasetHealth(baseUrl, fetchWithHeaders, datasetInfo.dataset_repo_id)
      .then((result) => {
        if (result.success) {
          setHealth(result);
        }
      })
      .catch((err) => console.error("Health check failed:", err))
      .finally(() => setCheckingHealth(false));
  }, [datasetInfo?.dataset_repo_id, baseUrl, fetchWithHeaders]);

  const openInHubViewer = (repoId: string) => {
    const spacePath = `/spaces/lerobot/visualize_dataset?path=${encodeURIComponent(`/${repoId}`)}`;
    // The user owns/manages the dataset (it appears under their hub
    // listing), so login-redirect always works whether public or
    // private. Avoids passing `private` through navigation state.
    const target = `https://huggingface.co/login?next=${encodeURIComponent(spacePath)}`;
    window.open(target, "_blank", "noopener,noreferrer");
  };

  const handleUploadToHub = async () => {
    if (!datasetInfo) return;

    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(false);
    setUploadProgress({ phase: "准备上传…", percent: 0, current: 0, total: 0 });
    followUploadProgress();

    const stopFollowing = () => {
      progressStream.current?.close();
      progressStream.current = null;
    };

    try {
      const response = await fetchWithHeaders(`${baseUrl}/upload-dataset`, {
        method: "POST",
        body: JSON.stringify({
          dataset_repo_id: datasetInfo.dataset_repo_id,
          tags: ["robotics", "lerobot"],
          private: false,
        }),
      });

      const data = await response.json();
      if (response.ok && data.success) {
        // The stream's completed event normally gets here first; this covers the
        // case where the subscription never came up.
        stopFollowing();
        setUploadSuccess(true);
        setUploadProgress({
          phase: "上传完成",
          percent: 100,
          current: 0,
          total: 0,
        });
        toast({
          title: "上传成功",
          description: `${datasetInfo.dataset_repo_id} 已上传到 HuggingFace Hub。`,
        });
        loadDatasetInfo();
      } else {
        stopFollowing();
        setUploadError(data.message || "上传失败");
        toast({
          title: "上传失败",
          description: data.docs_url ? (
            <span>
              {data.message || "上传失败"}{" "}
              <a
                href={data.docs_url}
                target="_blank"
                rel="noopener noreferrer"
                className="underline font-medium"
              >
                查看配置说明
              </a>
            </span>
          ) : (
            data.message || "上传失败"
          ),
          variant: "destructive",
        });
      }
    } catch (error) {
      console.error("Error uploading dataset:", error);
      stopFollowing();
      setUploadError("无法连接后端服务");
      toast({
        title: "连接错误",
        description: "无法连接后端服务。",
        variant: "destructive",
      });
    } finally {
      setIsUploading(false);
    }
  };

  const handleSkipUpload = () => {
    toast({
      title: "已跳过上传",
      description: "数据集已保存在本地，之后仍可手动上传。",
    });
    navigate("/");
  };

  const handleDeleteDataset = async () => {
    if (!datasetInfo) return;
    setIsDeleting(true);
    try {
      const response = await fetchWithHeaders(`${baseUrl}/delete-dataset`, {
        method: "POST",
        body: JSON.stringify({ dataset_repo_id: datasetInfo.dataset_repo_id }),
      });
      const data = await response.json();
      if (response.ok && data.success) {
        toast({
          title: "数据集已删除",
          description: `${datasetInfo.dataset_repo_id} 已从磁盘删除。`,
        });
        navigate("/");
      } else {
        toast({
          title: "删除失败",
          description: data.message || "无法删除数据集。",
          variant: "destructive",
        });
      }
    } catch (error) {
      toast({
        title: "连接错误",
        description: "无法连接后端服务。",
        variant: "destructive",
      });
    } finally {
      setIsDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  const handleDeleteSelectedEpisodes = async () => {
    if (!datasetInfo || selectedEpisodes.size === 0) return;
    const repoId = datasetInfo.dataset_repo_id;
    const indices = [...selectedEpisodes].sort((a, b) => a - b);
    setIsDeletingEpisode(true);
    setShowDeleteEpisodesConfirm(false);
    try {
      const response = await fetchWithHeaders(`${baseUrl}/delete-episode`, {
        method: "POST",
        body: JSON.stringify({
          dataset_repo_id: repoId,
          episode_indices: indices,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        toast({
          title: "删除失败",
          description: data.message || "无法删除所选分集。",
          variant: "destructive",
        });
        setIsDeletingEpisode(false);
        return;
      }

      if (!data.async) {
        // Legacy v2 layout finishes inside the request, so there is nothing to stream.
        toast({ title: "已删除分集", description: data.message });
        setSelectedEpisodes(new Set());
        await loadDatasetInfo();
        setIsDeletingEpisode(false);
        return;
      }

      // The rebuild runs on a worker thread and the POST returns immediately, so
      // progress arrives over the same SSE stream the repair flow uses.
      setRepairProgress({
        active: true,
        phase: "开始…",
        percent: 0,
        current: 0,
        total: 0,
        dataset_repo_id: repoId,
        error: null,
        completed: false,
      });
      const eventSource = new EventSource(`${baseUrl}/repair-progress`);
      eventSource.onmessage = (event) => {
        const progress: RepairProgress = JSON.parse(event.data);
        setRepairProgress(progress);
        if (progress.completed || progress.error) {
          eventSource.close();
          setIsDeletingEpisode(false);
          if (progress.error) {
            toast({
              title: "删除失败",
              description: progress.error,
              variant: "destructive",
            });
          } else {
            toast({ title: "已删除分集", description: progress.phase });
          }
          setSelectedEpisodes(new Set());
          loadDatasetInfo();
          checkDatasetHealth(baseUrl, fetchWithHeaders, repoId).then(setHealth);
        }
      };
      eventSource.onerror = () => {
        eventSource.close();
        setIsDeletingEpisode(false);
        toast({
          title: "进度中断",
          description: "重建可能仍在进行，刷新数据集查看结果。",
          variant: "destructive",
        });
        loadDatasetInfo();
      };
    } catch (error) {
      toast({
        title: "连接错误",
        description: "无法连接后端服务。",
        variant: "destructive",
      });
      setIsDeletingEpisode(false);
    }
  };

  const toggleEpisode = (index: number) => {
    setSelectedEpisodes((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const episodeCount = datasetInfo
    ? datasetInfo.saved_episodes || datasetInfo.num_episodes
    : 0;

  const fps = datasetInfo?.fps || 0;
  const episodeRows =
    datasetInfo?.episodes && datasetInfo.episodes.length > 0
      ? datasetInfo.episodes
      : Array.from({ length: episodeCount }, (_, index) => ({
          index,
          length: 0,
        }));
  const sortedLengths = episodeRows
    .map((e) => e.length)
    .filter((n) => n > 0)
    .sort((a, b) => a - b);
  const medianLength = sortedLengths.length
    ? sortedLengths[Math.floor(sortedLengths.length / 2)]
    : 0;
  const meanLength = sortedLengths.length
    ? Math.round(sortedLengths.reduce((a, b) => a + b, 0) / sortedLengths.length)
    : 0;
  const lengthStd =
    sortedLengths.length && meanLength
      ? Math.round(
          Math.sqrt(
            sortedLengths.reduce((s, v) => s + (v - meanLength) ** 2, 0) /
              sortedLengths.length
          )
        )
      : 0;

  const allEpisodesSelected =
    episodeCount > 0 && selectedEpisodes.size === episodeCount;

  const visibleEpisodes = (() => {
    const q = episodeQuery.trim().toLowerCase();
    const rows = q
      ? episodeRows.filter(
          ({ index, length }) =>
            String(index).includes(q) ||
            `#${String(index).padStart(3, "0")}`.includes(q) ||
            String(length).includes(q),
        )
      : episodeRows;
    const dir = episodeAsc ? 1 : -1;
    return [...rows].sort((a, b) =>
      episodeSort === "index"
        ? (a.index - b.index) * dir
        : (a.length - b.length) * dir,
    );
  })();

  const toggleEpisodeSort = (field: "index" | "length") => {
    if (episodeSort === field) {
      setEpisodeAsc((v) => !v);
    } else {
      setEpisodeSort(field);
      setEpisodeAsc(field === "index");
    }
  };

  const toggleAllEpisodes = () => {
    setSelectedEpisodes(
      allEpisodesSelected
        ? new Set()
        : new Set(Array.from({ length: episodeCount }, (_, i) => i)),
    );
  };

  const handleRepairDataset = async () => {
    if (!datasetInfo) return;
    setIsRepairing(true);
    setRepairProgress({
      active: true,
      phase: "开始…",
      percent: 0,
      current: 0,
      total: 0,
      dataset_repo_id: datasetInfo.dataset_repo_id,
      error: null,
      completed: false,
    });

    try {
      const response = await fetchWithHeaders(`${baseUrl}/repair-dataset`, {
        method: "POST",
        body: JSON.stringify({ dataset_repo_id: datasetInfo.dataset_repo_id }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        toast({
          title: "修复失败",
          description: data.message || "无法启动修复",
          variant: "destructive",
        });
        setIsRepairing(false);
        return;
      }

      // Poll repair progress via SSE
      const eventSource = new EventSource(`${baseUrl}/repair-progress`);
      eventSource.onmessage = (event) => {
        const progress: RepairProgress = JSON.parse(event.data);
        setRepairProgress(progress);
        if (progress.completed || progress.error) {
          eventSource.close();
          setIsRepairing(false);
          if (progress.error) {
            toast({
              title: "修复失败",
              description: progress.error,
              variant: "destructive",
            });
          } else {
            toast({ title: "修复完成", description: "数据集已修复。" });
            // Re-check health and reload info
            loadDatasetInfo();
            checkDatasetHealth(
              baseUrl,
              fetchWithHeaders,
              datasetInfo.dataset_repo_id,
            ).then(setHealth);
          }
        }
      };
      eventSource.onerror = () => {
        eventSource.close();
        setIsRepairing(false);
      };
    } catch (error) {
      toast({
        title: "连接错误",
        description: "无法连接后端服务。",
        variant: "destructive",
      });
      setIsRepairing(false);
    }
  };

  // Show loading state while fetching dataset info
  if (isLoadingDatasetInfo) {
    return (
      <div className="leforge-page min-h-screen text-slate-900 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <p className="text-lg">正在加载数据集信息…</p>
        </div>
      </div>
    );
  }

  // No dataset picked (deep link, or arrived just to merge): merging works on a
  // selection of its own, so don't hold it behind a dataset detail view.
  if (!datasetInfo) {
    return (
      <div className="leforge-page min-h-screen text-slate-900 p-8">
        <div className="max-w-[1440px] mx-auto">
          <div className="flex items-center gap-4 mb-6">
            <Button
              onClick={() => navigate("/")}
              variant="outline"
              className="border-sky-400 text-slate-700 hover:text-slate-900"
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              返回首页
            </Button>
            <Logo iconOnly />
            <h1 className="text-3xl font-bold tracking-tight">数据集 Datasets</h1>
          </div>
          {(() => {
            const viewTab: TabKey = tab === "tools" ? "tools" : "scoring";
            return (
              <>
                <TabBar value={viewTab} onChange={setTab} tabs={TOOL_TABS} />
                <section className={viewTab === "scoring" ? "" : "hidden"}>
                  <div
                    id="dataset-scoring"
                    className="grid gap-6 xl:grid-cols-2 xl:items-start"
                  >
                    <RolloutScoreCard initialRepoId={scoreRepoId} />
                    <SarmTrainCard initialRepoId={scoreRepoId} />
                  </div>
                </section>
                <section className={viewTab === "tools" ? "" : "hidden"}>
                  <div className="grid gap-6 xl:grid-cols-2 xl:items-start">
                    <DatasetTransferSection />
                    <MergeSection />
                  </div>
                </section>
              </>
            );
          })()}
        </div>
      </div>
    );
  }

  const isAlreadyOnHub = datasetInfo.source === "both";
  const onHub = uploadSuccess || isAlreadyOnHub;

  // One status, derived from the server's upload progress rather than local
  // guesses, so a refresh or a second browser tab shows the truth.
  const uploadStatus = isUploading
    ? {
        text: `上传中 ${uploadProgress.percent}%`,
        cls: "border-blue-600/50 bg-blue-100 text-blue-700",
      }
    : uploadError
      ? {
          text: "上传失败",
          cls: "border-red-600/50 bg-red-100 text-red-700",
        }
      : onHub
        ? {
            text: "已上传到 Hub",
            cls: "border-green-600/50 bg-green-100 text-green-700",
          }
        : {
            text: "仅保存在本地",
            cls: "border-sky-300 bg-sky-50 text-slate-600",
          };

  return (
    <div className="leforge-page min-h-screen text-slate-900 p-8">
      <div className="max-w-[1440px] mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <Button
              onClick={() => navigate("/")}
              variant="outline"
              className="border-sky-400 hover:border-gray-200 text-slate-700 hover:text-slate-900"
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              返回首页
            </Button>
            <Button
              onClick={() => setShowDeleteConfirm(true)}
              variant="outline"
              size="icon"
              disabled={isDeleting}
              aria-label="从磁盘删除数据集"
              className="border-red-500/40 text-red-700 hover:border-red-400 hover:text-red-700 hover:bg-red-100"
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>

          <div className="flex items-center gap-3">
            {onHub ? (
              <CheckCircle className="w-8 h-8 text-green-500" />
            ) : (
              <Database className="w-8 h-8 text-blue-500" />
            )}
            <h1 className="text-3xl font-bold">数据集 Datasets</h1>
          </div>
        </div>

        {/* 身份条：任何标签下都能看到的关键信息与主操作 */}
        <section className="rounded-xl border border-sky-300 bg-sky-100/70 p-5 backdrop-blur-xl">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                {onHub ? (
                  <CheckCircle className="h-5 w-5 shrink-0 text-green-600" />
                ) : (
                  <Database className="h-5 w-5 shrink-0 text-blue-500" />
                )}
                <span className="truncate font-mono text-lg font-semibold">
                  {datasetInfo.dataset_repo_id}
                </span>
              </div>
              <dl className="mt-3 flex flex-wrap gap-x-8 gap-y-2">
                <Stat label="集数" value={String(episodeCount)} />
                <Stat label="帧率" value={fps ? `${fps} FPS` : "-"} />
                <Stat
                  label="平均长度"
                  value={meanLength ? `${meanLength} 帧` : "-"}
                  sub={meanLength ? `±${lengthStd}` : undefined}
                />
                <Stat label="机器人" value={datasetInfo.robot_type || "-"} />
                <Stat
                  label="任务"
                  value={datasetInfo.tasks?.[0]?.task ?? "-"}
                  sub={
                    datasetInfo.tasks?.length
                      ? `${datasetInfo.tasks.length} 个`
                      : undefined
                  }
                />
              </dl>
            </div>

            <div className="flex flex-col items-end gap-3">
              <div className="flex flex-wrap justify-end gap-2">
                <span
                  className={`rounded-full border px-3 py-1 text-xs ${uploadStatus.cls}`}
                >
                  {uploadStatus.text}
                </span>
                {checkingHealth ? (
                  <span className="rounded-full border border-sky-300 px-3 py-1 text-xs text-slate-600">
                    完整性检查中…
                  </span>
                ) : health ? (
                  <span
                    className={`rounded-full border px-3 py-1 text-xs ${
                      health.healthy
                        ? "border-green-600/50 bg-green-100 text-green-700"
                        : "border-red-600/50 bg-red-100 text-red-700"
                    }`}
                  >
                    {health.healthy ? "完整性 正常" : "完整性 异常"}
                  </span>
                ) : null}
                {scoredBackends.includes("robometer") ? (
                  <span className="rounded-full border border-purple-600/50 bg-purple-100 px-3 py-1 text-xs text-purple-700">
                    Robometer 已评分
                  </span>
                ) : null}
                {scoredBackends.includes("sarm") ? (
                  <span className="rounded-full border border-cyan-600/50 bg-cyan-100 px-3 py-1 text-xs text-cyan-700">
                    SARM 已评分
                  </span>
                ) : null}
              </div>

              <div className="flex flex-wrap justify-end gap-3">
                <Button
                  onClick={() => setViewerOpen(true)}
                  variant="outline"
                  className="border-cyan-600/60 text-cyan-700 hover:bg-cyan-100"
                >
                  <ListVideo className="w-4 h-4 mr-2" />
                  本地可视化
                </Button>
                <Button
                  onClick={handleUploadToHub}
                  disabled={isUploading}
                  className="bg-blue-500 hover:bg-blue-600 text-white"
                >
                  {isUploading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Uploading…
                    </>
                  ) : (
                    <>
                      <UploadIcon className="w-4 h-4 mr-2" />
                      {isAlreadyOnHub ? "Re-sync to Hub" : "Upload to HuggingFace Hub"}
                    </>
                  )}
                </Button>
                {isAlreadyOnHub ? (
                  <Button
                    onClick={() => openInHubViewer(datasetInfo.dataset_repo_id)}
                    variant="outline"
                    className="border-sky-300 text-slate-700 hover:bg-sky-200"
                  >
                    <ExternalLink className="w-4 h-4 mr-2" />
                    View on Hub
                  </Button>
                ) : (
                  <Button
                    onClick={handleSkipUpload}
                    disabled={isUploading}
                    variant="outline"
                    className="border-sky-300 text-slate-700 hover:bg-sky-200"
                  >
                    Not Now
                  </Button>
                )}
              </div>
            </div>
          </div>

          {isUploading && (
            <div className="mt-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-slate-700">
                  {uploadProgress.phase || "准备中…"}
                </span>
                <span className="text-sm text-blue-700 font-mono">
                  {uploadProgress.percent}%
                </span>
              </div>
              <div className="w-full bg-sky-200 rounded-full h-2.5 overflow-hidden">
                <div
                  className="bg-blue-500 h-2.5 rounded-full transition-all duration-500 ease-out"
                  style={{ width: `${uploadProgress.percent}%` }}
                />
              </div>
              {uploadProgress.total > 0 && (
                <p className="text-xs text-slate-600 mt-1">
                  {uploadProgress.current} / {uploadProgress.total} 个文件
                </p>
              )}
            </div>
          )}

          {uploadError && !isUploading && (
            <div className="mt-4 rounded-lg border border-red-600/50 bg-red-100 p-3 text-sm text-red-700">
              上传失败：{uploadError}
            </div>
          )}
        </section>

        {datasetInfo.dataset_repo_id && (
          <DatasetViewer
            open={viewerOpen}
            onOpenChange={setViewerOpen}
            repoId={datasetInfo.dataset_repo_id}
          />
        )}

        <TabBar value={tab} onChange={setTab} tabs={DETAIL_TABS} />

        {/* 分集：搜索 + 排序 + 批量删除 */}
        <section className={tab === "episodes" ? "" : "hidden"}>
          <div className="rounded-xl border border-sky-300 bg-sky-100/70 backdrop-blur-xl">
            <div className="flex flex-wrap items-center gap-3 border-b border-sky-300/60 px-5 py-4">
              <ListVideo className="h-5 w-5 text-blue-700" />
              <h2 className="text-lg font-semibold text-slate-900">分集列表</h2>
              <span className="text-sm text-slate-600">
                {visibleEpisodes.length} / {episodeCount} 集
                {selectedEpisodes.size > 0 && (
                  <span className="text-red-700">
                    {" "}
                    · 已选 {selectedEpisodes.size}
                  </span>
                )}
              </span>
              <div className="ml-auto flex flex-wrap items-center gap-3">
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-600" />
                  <Input
                    value={episodeQuery}
                    onChange={(e) => setEpisodeQuery(e.target.value)}
                    placeholder="搜索集数或帧数…"
                    className="h-8 w-44 pl-8 bg-sky-50 border-sky-300 text-sm"
                    aria-label="搜索分集"
                  />
                </div>
                <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
                  <Checkbox
                    checked={allEpisodesSelected}
                    onCheckedChange={toggleAllEpisodes}
                    disabled={isDeletingEpisode}
                    aria-label="全选所有分集"
                  />
                  全选
                </label>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={isDeletingEpisode || selectedEpisodes.size === 0}
                  onClick={() => setShowDeleteEpisodesConfirm(true)}
                >
                  {isDeletingEpisode ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4 mr-2" />
                  )}
                  删除所选
                </Button>
              </div>
            </div>

            {isDeletingEpisode && repairProgress && (
              <div className="mx-5 mt-4 rounded-lg border border-sky-300 bg-sky-100/80 p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Loader2 className="w-4 h-4 text-blue-700 animate-spin" />
                    <span className="text-sm text-slate-700">
                      {repairProgress.phase}
                    </span>
                  </div>
                  <span className="text-sm text-blue-700 font-mono">
                    {repairProgress.percent}%
                  </span>
                </div>
                <div className="w-full bg-sky-200 rounded-full h-2.5 overflow-hidden">
                  <div
                    className="bg-blue-500 h-2.5 rounded-full transition-all duration-500 ease-out"
                    style={{ width: `${repairProgress.percent}%` }}
                  />
                </div>
                {repairProgress.total > 0 && (
                  <p className="text-xs text-slate-600 mt-1">
                    {repairProgress.current} / {repairProgress.total}
                  </p>
                )}
              </div>
            )}

            <div className="max-h-[60vh] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10 bg-sky-100/95 backdrop-blur">
                  <tr className="text-left text-xs text-slate-600">
                    <th className="w-10 px-4 py-2" />
                    <th className="px-4 py-2">
                      <button
                        type="button"
                        onClick={() => toggleEpisodeSort("index")}
                        className="flex items-center gap-1 hover:text-slate-900"
                      >
                        集数
                        {episodeSort === "index" ? (
                          episodeAsc ? (
                            <ChevronUp className="h-3 w-3" />
                          ) : (
                            <ChevronDown className="h-3 w-3" />
                          )
                        ) : null}
                      </button>
                    </th>
                    <th className="px-4 py-2">
                      <button
                        type="button"
                        onClick={() => toggleEpisodeSort("length")}
                        className="flex items-center gap-1 hover:text-slate-900"
                      >
                        帧数
                        {episodeSort === "length" ? (
                          episodeAsc ? (
                            <ChevronUp className="h-3 w-3" />
                          ) : (
                            <ChevronDown className="h-3 w-3" />
                          )
                        ) : null}
                      </button>
                    </th>
                    <th className="px-4 py-2">时长</th>
                    <th className="px-4 py-2">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleEpisodes.map(({ index, length }) => {
                    const isShort =
                      length > 0 && medianLength > 0 && length < medianLength * 0.5;
                    return (
                      <tr
                        key={index}
                        className={`border-t border-sky-300/60 ${
                          selectedEpisodes.has(index) ? "bg-red-100/40" : ""
                        }`}
                      >
                        <td className="px-4 py-2">
                          <Checkbox
                            checked={selectedEpisodes.has(index)}
                            onCheckedChange={() => toggleEpisode(index)}
                            disabled={isDeletingEpisode}
                            aria-label={`选择第 ${index} 集`}
                          />
                        </td>
                        <td className="px-4 py-2 font-mono text-green-700">
                          #{String(index).padStart(3, "0")}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-slate-900">
                          {length > 0 ? length : "—"}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-slate-600">
                          {length > 0 && fps ? `${(length / fps).toFixed(1)} 秒` : "—"}
                        </td>
                        <td className="px-4 py-2 text-xs">
                          {isShort ? (
                            <span className="text-amber-700">不足中位数一半</span>
                          ) : (
                            <span className="text-slate-600">正常</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {visibleEpisodes.length === 0 && (
                <p className="px-4 py-6 text-center text-sm text-slate-600">
                  没有匹配的分集。
                </p>
              )}
            </div>
          </div>
        </section>

        {/* 质量：完整性检查与内容质检 */}
        <section className={tab === "quality" ? "space-y-6" : "hidden"}>
          {checkingHealth && (
            <div className="bg-sky-100 rounded-lg p-4 border border-sky-300 flex items-center gap-3">
              <Loader2 className="w-5 h-5 text-blue-700 animate-spin" />
              <span className="text-slate-700">正在检查数据集完整性…</span>
            </div>
          )}

          {health && !health.healthy && (
            <DatasetHealthWarning
              health={health}
              isRepairing={isRepairing}
              repairProgress={repairProgress}
              onRepair={handleRepairDataset}
              onDelete={() => setShowDeleteConfirm(true)}
            />
          )}

          {health && health.healthy && (
            <div className="bg-green-100 border border-green-600/50 rounded-lg p-4 flex items-center gap-3">
              <CheckCircle className="w-5 h-5 text-green-700" />
              <span className="text-green-700 text-sm">
                数据集完整，{health.total_episodes} 集全部文件可读
              </span>
            </div>
          )}

          {datasetInfo.dataset_repo_id && (
            <DatasetSummaryCard datasetRepoId={datasetInfo.dataset_repo_id} />
          )}
        </section>

        {/* RA-BC：进度/成功率 + SARM 训练 */}
        <section className={tab === "scoring" ? "" : "hidden"}>
          <div
            id="dataset-scoring"
            className="grid gap-6 xl:grid-cols-2 xl:items-start"
          >
            <RolloutScoreCard initialRepoId={scoreRepoId} />
            <SarmTrainCard initialRepoId={scoreRepoId} />
          </div>
        </section>

        {/* 工具：外部格式转换与数据集合并 */}
        <section className={tab === "tools" ? "" : "hidden"}>
          <div className="grid gap-6 xl:grid-cols-2 xl:items-start">
            <DatasetTransferSection />
            <MergeSection />
          </div>
        </section>
      </div>

      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent className="bg-sky-100 border-sky-300 text-slate-900">
          <AlertDialogHeader>
            <AlertDialogTitle>从磁盘删除数据集？</AlertDialogTitle>
            <AlertDialogDescription className="text-slate-600">
              将从本地缓存中永久删除{" "}
              <span className="font-mono text-slate-900">
                {datasetInfo.dataset_repo_id}
              </span>
              ，此操作无法撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-sky-50 border-sky-300 text-slate-900 hover:bg-sky-200">
              保留数据集
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteDataset}
              disabled={isDeleting}
              className="bg-red-500 hover:bg-red-600 text-white"
            >
              {isDeleting ? "删除中…" : "删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={showDeleteEpisodesConfirm}
        onOpenChange={(open) => !open && setShowDeleteEpisodesConfirm(false)}
      >
        <AlertDialogContent className="bg-sky-100 border-sky-300 text-slate-900">
          <AlertDialogHeader>
            <AlertDialogTitle>
              删除选中的 {selectedEpisodes.size} 集？
            </AlertDialogTitle>
            <AlertDialogDescription className="text-slate-600">
              将删除第{" "}
              {[...selectedEpisodes]
                .sort((a, b) => a - b)
                .slice(0, 12)
                .join(", ")}
              {selectedEpisodes.size > 12
                ? ` 等 ${selectedEpisodes.size} 集`
                : ""}
              。原数据集备份在同级目录{" "}
              <code className="text-slate-700">
                {datasetInfo?.dataset_repo_id.split("/").pop() || "dataset"}
                __bak_del*
              </code>
              ，删掉备份前都可恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-sky-50 border-sky-300 text-slate-900 hover:bg-sky-200">
              取消
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteSelectedEpisodes}
              disabled={isDeletingEpisode}
              className="bg-red-500 hover:bg-red-600 text-white"
            >
              {isDeletingEpisode
                ? "重建中…"
                : `删除 ${selectedEpisodes.size} 集`}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default Upload;
