import type { DigitalTwinNode } from '../api/types'

export type GalaxyClusterId = 'family' | 'condition' | 'medicine' | 'conversation' | 'rag' | 'insight'

export interface GalaxyCluster {
  id: GalaxyClusterId
  label: string
  shortLabel: string
  caption: string
  color: string
  soft: string
  icon: string
  x: number
  y: number
}

export interface GalaxyOrbitNode {
  id: string
  label: string
  clusterId: GalaxyClusterId
  node: DigitalTwinNode | null
  guide: boolean
  x: number
  y: number
  z: number
  ring: number
}

export interface GalaxySnapshotDelta {
  addedNodeIds: Set<string>
  counts: Record<GalaxyClusterId, number>
}
