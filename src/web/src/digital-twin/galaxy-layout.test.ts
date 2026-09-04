import { describe, expect, it } from 'vitest'

import type { DigitalTwinNode, DigitalTwinResponse } from '../api/types'
import { buildGlobalOrbitNodes, buildLocalOrbitNodes, clusterForNode, GALAXY_CLUSTERS, snapshotDelta } from './galaxy-layout'

function node(id: string, category: DigitalTwinNode['category'], kind: DigitalTwinNode['kind'] = 'fact'): DigitalTwinNode {
  return { id, category, kind, label: id, status: 'CONFIRMED', source_kind: 'TEST', source_id: id, source_recorded_at: '2026-09-04T00:00:00Z', confidence: 1, vector_terms: [], vector_size: 0, projection: { x: 0, y: 0, z: 0 } }
}

function twin(nodes: DigitalTwinNode[]): DigitalTwinResponse {
  return { household_id: 'h1', generated_at: '2026-09-04T00:00:00Z', vector_backend: 'term_vector', vector_note: '', members: [], nodes, edges: [], stats: { member_count: 0, fact_count: 0, memory_count: 0, unconfirmed_count: 0, knowledge_count: 0, edge_count: 0 } }
}

describe('galaxy layout', () => {
  it('maps backend nodes into product clusters', () => {
    expect(clusterForNode(node('m', 'medication'))).toBe('medicine')
    expect(clusterForNode(node('k', 'knowledge', 'knowledge'))).toBe('rag')
    expect(clusterForNode(node('c', 'chat', 'memory'))).toBe('conversation')
  })

  it('lays local nodes on two rings', () => {
    const result = buildLocalOrbitNodes(Array.from({ length: 10 }, (_, index) => node(`n${index}`, 'medication')), 'medicine')
    expect(result).toHaveLength(10)
    expect(result.filter(item => item.ring === 1)).toHaveLength(7)
    expect(result.filter(item => item.ring === 2)).toHaveLength(3)
  })

  it('keeps overview density bounded and preserves backend depth', () => {
    const medicines = Array.from({ length: 9 }, (_, index) => ({ ...node(`m${index}`, 'medication'), projection: { x: 0, y: 0, z: index === 0 ? -.8 : .6 } }))
    const medicineCluster = GALAXY_CLUSTERS.find(cluster => cluster.id === 'medicine')!
    const result = buildGlobalOrbitNodes(medicines, medicineCluster)
    expect(result).toHaveLength(6)
    expect(result[0].z).toBe(-.8)
    expect(result.every(item => item.node)).toBe(true)
  })

  it('uses an asymmetric overview composition', () => {
    expect(GALAXY_CLUSTERS.find(cluster => cluster.id === 'condition')?.y).not.toBe(GALAXY_CLUSTERS.find(cluster => cluster.id === 'family')?.y)
    expect(GALAXY_CLUSTERS.find(cluster => cluster.id === 'conversation')?.x).not.toBe(100 - (GALAXY_CLUSTERS.find(cluster => cluster.id === 'medicine')?.x ?? 0))
  })

  it('reports only newly observed nodes by cluster', () => {
    const delta = snapshotDelta(twin([node('old', 'profile', 'member')]), twin([node('old', 'profile', 'member'), node('new', 'disease')]))
    expect(delta.addedNodeIds.has('new')).toBe(true)
    expect(delta.counts.condition).toBe(1)
  })
})
