import React, { useState } from "react";
import { Bot, Settings, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RobotRecord } from "@/hooks/useRobots";
import RobotSelector from "./RobotSelector";

interface RobotTileProps {
  robot: RobotRecord | null;
  selectedName: string | null;
  availableNames: string[];
  isLoading: boolean;
  onSelect: (name: string) => void;
  onCreateNew: (name: string) => Promise<boolean>;
  onConfigure: (name: string) => void;
  onTeleop: (robot: RobotRecord) => void;
  onDelete: (name: string) => void;
}

const RobotTile: React.FC<RobotTileProps> = ({
  robot,
  selectedName,
  availableNames,
  isLoading,
  onSelect,
  onCreateNew,
  onConfigure,
  onTeleop,
  onDelete,
}) => {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const teleopDisabled = !robot || !robot.is_clean;

  return (
    <div className="forge-tile flex flex-col gap-2 relative">
      <div className="flex items-center gap-1.5 h-10">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100">
          <Bot className="h-4 w-4 text-slate-700" />
        </span>
        <h3 className="font-semibold text-lg tracking-tight text-left whitespace-nowrap min-[1800px]:text-[15px]">机器人 Robot</h3>
        <div className="ml-auto flex items-center gap-1 min-w-0">
          {robot && (
            <div className="flex items-center gap-1 shrink-0">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-7 w-7 text-slate-700 hover:text-slate-900"
                    onClick={() => onConfigure(robot.name)}
                    aria-label="Configure"
                  >
                    <Settings className="w-4 h-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Configure (calibrate)</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-7 w-7 text-red-700 hover:text-red-700 hover:bg-red-100"
                    onClick={() => setConfirmDelete(true)}
                    aria-label="Delete robot"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Delete robot config</TooltipContent>
              </Tooltip>
            </div>
          )}
        </div>
      </div>

      <div className="flex items-stretch gap-2">
        <div className="min-w-0 flex-1">
          <RobotSelector
            selectedName={selectedName}
            availableNames={availableNames}
            onSelect={onSelect}
            onCreateNew={onCreateNew}
            isLoading={isLoading}
          />
        </div>

        {robot && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                onClick={() => onTeleop(robot)}
                disabled={teleopDisabled}
                className={`shrink-0 ${
                  teleopDisabled
                    ? "bg-red-100 hover:bg-red-100 text-red-700 cursor-not-allowed"
                    : "bg-yellow-500 hover:bg-yellow-600 text-[#1b1405]"
                }`}
              >
                Teleoperation
              </Button>
            </TooltipTrigger>
            {teleopDisabled && (
              <TooltipContent>Configure the robot first.</TooltipContent>
            )}
          </Tooltip>
        )}
      </div>

      {robot && (
        <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
          <DialogContent className="bg-sky-100 border-sky-200 text-slate-900">
            <DialogHeader>
              <DialogTitle>删除机器人配置？ Delete robot config?</DialogTitle>
              <DialogDescription className="text-slate-600">
                This deletes the robot config file from disk. Calibration files
                are not removed. This cannot be undone.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter className="flex gap-2 justify-end">
              <Button
                variant="outline"
                className="border-sky-300 text-slate-700"
                onClick={() => setConfirmDelete(false)}
              >
                Cancel
              </Button>
              <Button
                className="bg-red-500 hover:bg-red-600 text-white"
                onClick={async () => {
                  setConfirmDelete(false);
                  await onDelete(robot.name);
                }}
              >
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
};

export default RobotTile;
