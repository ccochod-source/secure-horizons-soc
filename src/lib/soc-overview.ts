export type SocOverview = {
  updatedAt: string;
  databaseConnected: boolean;
  pipelineConnected: boolean;
  agents: { id: string; name: string; role: string }[];
  reviews: { id: string; package: string; version: string; status: string }[];
  incidents: { id: string; title: string; severity: string; status: string; decision?: string }[];
  activity: { id: string; time: string; title: string; result: string }[];
  blockedActions: number | null;
  completedTests: number | null;
};

// Database connectivity is independent of agent integration. Seeded inventory,
// incidents and benchmarks are deliberately excluded until the real pipeline is wired.
export function unconnectedOverview(checkedAt: string): SocOverview {
  return {
    updatedAt: checkedAt,
    databaseConnected: true,
    pipelineConnected: false,
    agents: [], reviews: [], incidents: [], activity: [],
    blockedActions: null,
    completedTests: null,
  };
}
