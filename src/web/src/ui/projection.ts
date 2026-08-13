import type { HealthEvent } from '../api/types'

/**
 * 与后端 `app.projection.build_relationship_graph` 保持一致的客户端投影：
 * 只消费 API 已授权返回的已确认事件，被补偿的事件不进入当前事实。
 */

export interface DrugFact {
  name: string
  addedBy: string
}

export interface NamedFact {
  name: string
  addedBy: string
}

export interface PlanFact {
  drug: string
  schedule: string
  addedBy: string
}

export interface MemberFacts {
  drugs: DrugFact[]
  allergies: NamedFact[]
  diseases: NamedFact[]
  plans: PlanFact[]
  caregivers: string[]
  eventsCount: number
}

export function buildFactsFromTimeline(events: HealthEvent[]): MemberFacts {
  const compensated = new Set<string>()
  for (const event of events) {
    if (event.event_type === 'COMPENSATION' && event.compensates_event_id) {
      compensated.add(event.compensates_event_id)
    }
  }

  let drugs: DrugFact[] = []
  let allergies: NamedFact[] = []
  let diseases: NamedFact[] = []
  const plans: PlanFact[] = []
  const caregivers: string[] = []

  for (const event of events) {
    if (compensated.has(event.id)) continue
    const payload = (event.payload ?? {}) as Record<string, unknown>

    switch (event.event_type) {
      case 'medication_added':
        drugs.push({ name: String(payload.drug ?? '未命名药品'), addedBy: event.id })
        break
      case 'medication_confirmed': {
        // 视觉复核确认入档的事件载荷用 drug_name（HCT-207）
        const confirmedName = payload.drug_name ?? payload.drug
        if (confirmedName) drugs.push({ name: String(confirmedName), addedBy: event.id })
        break
      }
      case 'medication_stopped': {
        const stoppedName = String(payload.drug_name ?? payload.drug ?? '')
        drugs = drugs.filter(item => item.name !== stoppedName)
        break
      }
      case 'allergy_added':
        allergies.push({ name: String(payload.allergy ?? ''), addedBy: event.id })
        break
      case 'allergy_removed':
        allergies = allergies.filter(item => item.name !== String(payload.allergy ?? ''))
        break
      case 'disease_added':
        diseases.push({ name: String(payload.disease ?? ''), addedBy: event.id })
        break
      case 'disease_resolved':
        diseases = diseases.filter(item => item.name !== String(payload.disease ?? ''))
        break
      case 'plan_created':
      case 'plan_updated':
        plans.push({
          drug: String(payload.drug ?? '未命名药品'),
          schedule: String(payload.schedule ?? '未填写安排'),
          addedBy: event.id,
        })
        break
      case 'caregiver_assigned':
        caregivers.push(String(payload.caregiver_id ?? ''))
        break
      default:
        break
    }
  }

  return {
    drugs,
    allergies,
    diseases,
    plans,
    caregivers: [...new Set(caregivers.filter(Boolean))],
    eventsCount: events.length,
  }
}
