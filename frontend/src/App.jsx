import { useEffect, useState } from 'react'
import DashboardPage from './DashboardPage.jsx'
import { AccessPage, AddMemberPage, EvidencePage, EventsPage, MemberPage, RiskPage } from './template-pages.jsx'
import { EmergencyContactsPage, SettingsPage } from './settings-pages.jsx'
import { AddHealthEventPage, ReportComparisonPage, ReportsPage } from './health-pages.jsx'
import { AssistantPage, BigScreenPage, CarePlanPage, GraphPage, ModelLabPage, ReviewCenterPage, SafetyCenterPage, ScanCenterPage } from './core-pages.jsx'

function resolveRoute(hash) {
  const value = decodeURIComponent(hash || '')
  if (value.includes('视觉扫描中心')) return 'scan'
  if (value.includes('复核中心')) return 'review'
  if (value.includes('家庭健康图谱') || value.includes('关系图谱')) return 'graph'
  if (value.includes('用药安全中心')) return 'safety'
  if (value.includes('健康计划中心')) return 'plan'
  if (value.includes('本地健康助手')) return 'assistant'
  if (value.includes('家庭健康大屏')) return 'bigscreen'
  if (value.includes('模型实验室')) return 'model'
  if (value.includes('添加健康事件')) return 'addEvent'
  if (value.includes('报告对比')) return 'comparison'
  if (value.includes('健康报告')) return 'reports'
  if (value.includes('紧急联系人')) return 'emergency'
  if (value.includes('系统设置')) return 'settings'
  if (value.includes('权限')) return 'access'
  if (value.includes('家庭成员')) return 'member'
  if (value.includes('事件')) return 'events'
  if (value.includes('用药')) return 'risk'
  if (value.includes('报告') || value.includes('证据')) return 'evidence'
  return 'dashboard'
}

function selectedMember(hash) {
  const [, member] = decodeURIComponent(hash || '').split('/')
  return member || '父亲'
}

export default function App() {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => { const update = () => setHash(window.location.hash); window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update) }, [])
  const route = resolveRoute(hash)
  if (route === 'scan') return <ScanCenterPage />
  if (route === 'review') return <ReviewCenterPage />
  if (route === 'graph') return <GraphPage />
  if (route === 'safety') return <SafetyCenterPage />
  if (route === 'plan') return <CarePlanPage />
  if (route === 'assistant') return <AssistantPage />
  if (route === 'bigscreen') return <BigScreenPage />
  if (route === 'model') return <ModelLabPage />
  if (route === 'addEvent') return <AddHealthEventPage />
  if (route === 'comparison') return <ReportComparisonPage />
  if (route === 'reports') return <ReportsPage />
  if (route === 'emergency') return <EmergencyContactsPage />
  if (route === 'settings') return <SettingsPage />
  if (route === 'access') return <AccessPage />
  if (route === 'member') return <MemberPage memberKey={selectedMember(hash)} />
  if (route === 'events') return <EventsPage />
  if (route === 'risk') return <RiskPage />
  if (route === 'evidence') return <EvidencePage />
  return <DashboardPage />
}


