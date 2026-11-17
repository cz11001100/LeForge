import React from 'react';
import EssentialsCard from './config/EssentialsCard';
import GrootCard from './config/GrootCard';
import AdvancedCard from './config/AdvancedCard';
import TargetCard from './config/TargetCard';
import { ConfigComponentProps } from './types';
import { DatasetItem } from '@/lib/replayApi';
import { RunnerFlavor, SSHConfig } from '@/lib/jobsApi';

interface ConfigurationTabProps extends ConfigComponentProps {
  datasets: DatasetItem[];
  datasetsLoading: boolean;
  authenticated: boolean;
  flavors: RunnerFlavor[];
  hardwareLoading: boolean;
  sshConfigs: SSHConfig[];
  sshConfigsLoading: boolean;
}

const ConfigurationTab: React.FC<ConfigurationTabProps> = ({
  config,
  updateConfig,
  datasets,
  datasetsLoading,
  authenticated,
  flavors,
  hardwareLoading,
  sshConfigs,
  sshConfigsLoading,
}) => {
  return (
    <div className="mx-auto max-w-[1360px] space-y-6">
      <div className="grid gap-6 xl:grid-cols-2 xl:items-start">
        <TargetCard
          config={config}
          updateConfig={updateConfig}
          authenticated={authenticated}
          flavors={flavors}
          loading={hardwareLoading}
          sshConfigs={sshConfigs}
          sshConfigsLoading={sshConfigsLoading}
        />
        <div className="space-y-6">
          <EssentialsCard
            config={config}
            updateConfig={updateConfig}
            datasets={datasets}
            datasetsLoading={datasetsLoading}
          />
          <GrootCard config={config} updateConfig={updateConfig} />
        </div>
      </div>
      <AdvancedCard config={config} updateConfig={updateConfig} />
    </div>
  );
};

export default ConfigurationTab;
