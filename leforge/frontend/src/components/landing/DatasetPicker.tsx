import React, { useState } from "react";
import { Plus, ExternalLink, Download, Loader2 } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DatasetItem } from "@/lib/replayApi";

interface DatasetPickerProps {
  datasets: DatasetItem[];
  loading: boolean;
  onPickExisting: (item: DatasetItem) => void;
  onCreateNew: (name: string) => void;
  onOpenCustom: (repoId: string) => void;
  onImportHub: (repoId: string) => void;
  children: React.ReactNode;
}

const REPO_ID_RE = /^[\w.\-]+\/[\w.\-]+$/;
const NAME_RE = /^[A-Za-z0-9._-]+$/;

const DatasetPicker: React.FC<DatasetPickerProps> = ({
  datasets,
  loading,
  onPickExisting,
  onCreateNew,
  onOpenCustom,
  onImportHub,
  children,
}) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hubRepo, setHubRepo] = useState("");

  const trimmed = query.trim();
  const matchesExisting = datasets.some(
    (d) => d.repo_id.toLowerCase() === trimmed.toLowerCase(),
  );
  const isRepoId = REPO_ID_RE.test(trimmed);
  const isName = NAME_RE.test(trimmed) && !trimmed.includes("/");
  const canCreate = trimmed.length > 0 && isName && !matchesExisting;
  const canOpenCustom = isRepoId && !matchesExisting;

  const createDisabled = matchesExisting || (trimmed !== "" && !canCreate);
  const createLabel = matchesExisting
    ? "Already exists"
    : trimmed === ""
      ? "Create new dataset…"
      : canCreate
        ? `Create "${trimmed}"`
        : 'Use a name without "/"';

  const handleFooterCreate = () => {
    if (createDisabled) return;
    onCreateNew(trimmed);
    reset();
  };

  const localDatasets = datasets.filter((d) => d.source === "local" || d.source === "both");
  const hubDatasets = datasets.filter((d) => d.source === "hub");

  const reset = () => {
    setQuery("");
    setOpen(false);
  };

  const handlePick = (item: DatasetItem) => {
    onPickExisting(item);
    reset();
  };

  const handleCreate = () => {
    if (!canCreate) return;
    onCreateNew(trimmed);
    reset();
  };

  const handleOpenCustom = () => {
    if (!canOpenCustom) return;
    onOpenCustom(trimmed);
    reset();
  };

  const renderItem = (d: DatasetItem) => (
    <CommandItem
      key={d.repo_id}
      value={d.repo_id}
      onSelect={() => handlePick(d)}
      className="text-slate-900 aria-selected:bg-sky-200"
    >
      <span className="flex-1 truncate">{d.repo_id}</span>
      {d.source === "both" && (
        <span className="text-xs text-slate-600 mr-2">on Hub</span>
      )}
      {d.private && (
        <span className="text-xs text-amber-700">private</span>
      )}
    </CommandItem>
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent
        className="w-[320px] p-0 bg-sky-50 border-sky-300 text-slate-900"
        align="end"
      >
        <Command className="bg-sky-50">
          <CommandInput
            placeholder="Search, type a new name, or org/name…"
            value={query}
            onValueChange={(v) => setQuery(v.replace(/[^A-Za-z0-9._\-/]/g, "_"))}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              if (canCreate) {
                e.preventDefault();
                handleCreate();
              } else if (canOpenCustom) {
                e.preventDefault();
                handleOpenCustom();
              }
            }}
            className="text-slate-900"
          />
          <CommandList>
            {datasets.length === 0 && !canCreate && !canOpenCustom && (
              <CommandEmpty className="py-6 text-sm text-slate-600 text-center">
                {loading ? (
                  <div className="flex flex-col items-center gap-2">
                    <Loader2 className="h-5 w-5 animate-spin text-blue-700" />
                    <span>Loading datasets…</span>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-1">
                    <span className="font-medium">No datasets yet</span>
                    <span className="text-xs">Type a name above to create one</span>
                  </div>
                )}
              </CommandEmpty>
            )}
            {localDatasets.length > 0 && (
              <CommandGroup heading="Local">
                {localDatasets.map(renderItem)}
              </CommandGroup>
            )}
            {hubDatasets.length > 0 && (
              <CommandGroup heading="Hugging Face">
                {hubDatasets.map(renderItem)}
              </CommandGroup>
            )}
            {canOpenCustom && (
              <CommandGroup heading="Custom repo">
                <CommandItem
                  value={`__open__${trimmed}`}
                  onSelect={handleOpenCustom}
                  className="text-slate-900 aria-selected:bg-sky-200"
                >
                  <ExternalLink className="mr-2 h-4 w-4" />
                  在网页打开 &quot;{trimmed}&quot;
                </CommandItem>
              </CommandGroup>
            )}
          </CommandList>
          <button
            type="button"
            onClick={handleFooterCreate}
            disabled={createDisabled}
            className="flex w-full items-center gap-2 border-t border-sky-300 px-3 py-2 text-sm text-slate-900 hover:bg-sky-200 disabled:cursor-not-allowed disabled:text-slate-600 disabled:hover:bg-transparent"
          >
            <Plus className="h-4 w-4" />
            {createLabel}
          </button>
        </Command>
        <div className="border-t border-sky-300 p-3 space-y-1.5">
          <Label className="text-xs text-slate-600">从 HuggingFace Hub 导入</Label>
          <div className="flex gap-1.5">
            <Input
              value={hubRepo}
              onChange={(e) =>
                setHubRepo(e.target.value.replace(/[^A-Za-z0-9._\-/]/g, "_"))
              }
              placeholder="org/name"
              className="bg-sky-50 border-sky-300 text-slate-900 text-sm h-8"
            />
            <Button
              size="sm"
              className="h-8 shrink-0 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
              disabled={!REPO_ID_RE.test(hubRepo.trim())}
              onClick={() => {
                const id = hubRepo.trim();
                if (!REPO_ID_RE.test(id)) return;
                onImportHub(id);
                setHubRepo("");
                setOpen(false);
              }}
            >
              <Download className="mr-1 h-3.5 w-3.5" />
              导入
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default DatasetPicker;
