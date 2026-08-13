import { useEffect, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  Camera,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  CircleAlert,
  CircleCheck,
  Clock3,
  Cloud,
  Database,
  Eye,
  FileCheck2,
  FileSearch,
  FileText,
  Gauge,
  GitCompareArrows,
  HeartPulse,
  Info,
  Layers3,
  Link2,
  LockKeyhole,
  MessageCircle,
  Network,
  RotateCcw,
  ScanLine,
  ScanSearch,
  SearchCheck,
  ServerCog,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Tags,
  Timer,
  UploadCloud,
  UserCheck,
  UsersRound,
  Workflow,
  X,
  Zap,
} from 'lucide-react'
import { PageFrame } from './template-pages.jsx'
import { FamilyAvatar } from './avatar-system.jsx'
import { ArtModal } from './art-modal.jsx'

const members = ['父亲', '母亲', '我', '孩子']
const memberAvatarKeys = { 父亲: 'father', 母亲: 'mother', 我: 'self', 孩子: 'child' }

function PageIntro({ eyebrow, title, description, actions }) {
  return <div className="core-page-intro">
    <div>
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
    {actions && <div className="core-page-actions">{actions}</div>}
  </div>
}

function StatusBadge({ tone = 'info', children }) {
  return <span className={`core-status ${tone}`}><i />{children}</span>
}

function SectionTitle({ icon: Icon, title, detail, action }) {
  return <div className="core-section-title">
    <div><h2><Icon size={19} /> {title}</h2>{detail && <p>{detail}</p>}</div>
    {action}
  </div>
}

function MetricTile({ label, value, detail, tone = 'blue', icon: Icon = Activity }) {
  return <article className={`core-metric-tile ${tone}`}><span className="core-metric-icon"><Icon size={17} /></span><div><p>{label}</p><strong>{value}</strong><small>{detail}</small></div></article>
}

export function ScanCenterPage() {
  const [member, setMember] = useState('父亲')
  const [inputType, setInputType] = useState('药盒拍照')
  const [started, setStarted] = useState(false)
  const [queued, setQueued] = useState(false)
  const [resultOpen, setResultOpen] = useState(false)
  const inputs = [['药盒拍照', Camera], ['报告上传', UploadCloud], ['短视频抽帧', ScanLine]]
  return <PageFrame title="视觉扫描中心"><div className="core-page scan-page">
    <PageIntro eyebrow="P0 · 多证据视觉录入" title="视觉扫描中心" description="先做质量检查，再由 OCR、条码、包装特征和本地主数据共同生成候选。未确认结果不会进入健康档案。" actions={<><StatusBadge tone="good">本地视觉服务在线</StatusBadge><a className="core-outline-button" href="#复核中心"><FileCheck2 size={16} /> 待复核 3</a></>} />
    <div className="workflow-strip"><span className="active"><b>1</b> 选择成员</span><i /><span className={started ? 'active' : ''}><b>2</b> 质量检查</span><i /><span className={started ? 'active' : ''}><b>3</b> 多证据识别</span><i /><span className={queued ? 'active' : ''}><b>4</b> 人工复核</span></div>
    <div className="core-two-column scan-layout"><div className="core-stack">
      <section className="core-surface"><SectionTitle icon={UsersRound} title="选择成员与输入方式" detail="识别任务只读取当前成员的已授权资料。" /><div className="member-chip-row">{members.map(item => <button key={item} className={member === item ? 'selected' : ''} onClick={() => setMember(item)}><FamilyAvatar memberKey={memberAvatarKeys[item]} name={item} className="member-chip-avatar" />{item}<Check size={14} /></button>)}</div><div className="input-method-grid">{inputs.map(([label, Icon]) => <button key={label} className={inputType === label ? 'selected' : ''} onClick={() => setInputType(label)}><Icon size={23} /><span>{label}</span><small>{label === '药盒拍照' ? 'OCR-first' : label === '报告上传' ? 'PDF / 图片' : '关键帧去重'}</small></button>)}</div></section>
      <section className="core-surface scan-dropzone"><div className="scan-orb"><ScanSearch size={30} /></div><p className="eyebrow">{inputType} · {member}</p><h2>{started ? '本地处理已完成，等待人工确认' : '拍照、上传，或拖入文件'}</h2><p>支持药盒、处方单、检验报告与短视频。原始文件只在本地家庭可信域处理。</p><button className="core-primary-button" onClick={() => { setStarted(true); setQueued(true); setResultOpen(true) }}><ScanLine size={17} /> {started ? '重新处理' : '开始本地识别'}</button><div className="scan-dropzone-foot"><span><LockKeyhole size={14} /> 不出网</span><span><Clock3 size={14} /> 预计 8–20 秒</span><span><ShieldCheck size={14} /> 可撤销</span></div></section>
    </div><aside className="core-stack">
      <section className="core-surface quality-card"><SectionTitle icon={Gauge} title="质量门控" detail="示例任务 · 本地 OpenCV" /><div className="quality-score"><strong>{started ? '84' : '—'}</strong><span>/100</span><StatusBadge tone={started ? 'good' : 'muted'}>{started ? '通过，可进入识别' : '等待输入'}</StatusBadge></div><div className="quality-bars"><div><span>清晰度</span><b><i style={{ width: started ? '88%' : '0%' }} /></b><em>{started ? '88' : '—'}</em></div><div><span>遮挡</span><b><i style={{ width: started ? '72%' : '0%' }} /></b><em>{started ? '低' : '—'}</em></div><div><span>光照</span><b><i style={{ width: started ? '79%' : '0%' }} /></b><em>{started ? '稳定' : '—'}</em></div></div><p className="core-note"><Info size={15} /> 质量不达标时只提示补拍，不会用低质量结果做风险计算。</p></section>
      <section className="core-surface evidence-preview"><SectionTitle icon={Layers3} title="多证据通道" detail="识别结果必须有来源" /><div className="evidence-channel"><span className="channel-icon ocr">Aa</span><div><strong>OCR 主链路</strong><small>{started ? '阿托伐他汀钙片 · 10mg' : '等待文本提取'}</small></div><StatusBadge tone={started ? 'good' : 'muted'}>{started ? '完成' : '待处理'}</StatusBadge></div><div className="evidence-channel"><span className="channel-icon barcode">▦</span><div><strong>条码 / 二维码</strong><small>{started ? '无可解码条码' : '等待检测'}</small></div><StatusBadge tone={started ? 'warn' : 'muted'}>{started ? '空' : '待处理'}</StatusBadge></div><div className="evidence-channel"><span className="channel-icon match">✦</span><div><strong>主数据匹配</strong><small>{started ? '候选 2 个 · 需要确认' : '等待融合'}</small></div><StatusBadge tone={started ? 'warn' : 'muted'}>{started ? 'REVIEW' : '待处理'}</StatusBadge></div><a className="core-text-link" href="#复核中心">查看识别详情 <ArrowRight size={15} /></a></section>
    </aside></div>
    <ArtModal open={resultOpen} onClose={() => setResultOpen(false)} icon={ScanSearch} eyebrow="本地视觉处理" title="识别任务已排入证据链" description={`${member} · ${inputType} · 预计 8–20 秒完成质量与多证据检查`}>
      <div className="art-modal-note"><ShieldCheck size={16} /><span>原始文件只在当前家庭可信域内处理，确认前不会写入健康档案。</span></div>
      <div className="art-modal-list"><div className="art-modal-list-row"><div><strong>质量门控</strong><small>清晰度、遮挡与光照检查</small></div><StatusBadge tone="good">已通过</StatusBadge></div><div className="art-modal-list-row"><div><strong>多证据识别</strong><small>OCR、包装特征和主数据联合候选</small></div><StatusBadge tone="navy">处理中</StatusBadge></div><div className="art-modal-list-row"><div><strong>人工复核</strong><small>最终确认前保留可追溯入口</small></div><StatusBadge tone="muted">待处理</StatusBadge></div></div>
    </ArtModal>
  </div></PageFrame>
}

export function ReviewCenterPage() {
  const [confirmed, setConfirmed] = useState(false)
  const [corrected, setCorrected] = useState(false)
  const [training, setTraining] = useState(false)
  const [reason, setReason] = useState('')
  return <PageFrame title="人工复核中心"><div className="core-page review-page">
    <PageIntro eyebrow="P0 · 确认前的最后一道门" title="人工复核中心" description="对照原始证据、候选和冲突原因。确认会追加健康事件，修正会保留 before / after 和审计记录。" actions={<StatusBadge tone="warn">待处理 3 条</StatusBadge>} />
    <div className="review-toolbar"><div><StatusBadge tone="warn">REVIEW</StatusBadge><span>识别任务 #VIS-2042</span><span>父亲 · 12 分钟前</span></div><button className="core-ghost-button"><RotateCcw size={16} /> 重新处理</button></div>
    <div className="review-grid"><section className="core-surface review-evidence"><SectionTitle icon={Eye} title="原始证据" detail="文件正文仅对当前授权操作者可见" /><div className="review-image"><div className="medicine-box"><span>ATV</span><strong>ATORVASTATIN<br />CALCIUM</strong><small>10 mg · 28 tablets</small></div><div className="scan-frame"><i /><i /><i /><i /><b>包装区域</b></div><span className="image-stamp"><LockKeyhole size={13} /> 本地预览</span></div><div className="source-list"><div><span>来源</span><strong>家属上传照片 · JPG</strong></div><div><span>质量</span><strong>84 / 100 · 通过</strong></div><div><span>模型版本</span><strong>OCR 0.4 · 规则匹配器 0.2</strong></div></div></section><section className="core-surface review-candidate"><SectionTitle icon={SearchCheck} title="候选与冲突解释" detail="最高候选也不能跳过人工确认" /><div className="candidate-list"><article className="candidate selected"><div><strong>阿托伐他汀钙片</strong><small>10mg × 28片 · 常见包装</small></div><span>主数据一致</span><b>候选 1</b></article><article className="candidate"><div><strong>阿托伐他汀片</strong><small>20mg × 14片 · 规格不一致</small></div><span>规格冲突</span><b>候选 2</b></article></div><div className="conflict-box"><ShieldAlert size={19} /><div><strong>需要确认的差异</strong><p>OCR 识别到“10mg”，包装特征与候选 1 一致；批号被反光遮挡，无法自动确认。</p></div></div><div className="review-fields"><label><span>药品名称</span><input defaultValue="阿托伐他汀钙片" /></label><label><span>规格</span><input defaultValue="10mg × 28片" /></label><label><span>有效期</span><input placeholder="无法识别，请手动补录" /></label></div></section></div>
    <section className="core-surface review-submit"><SectionTitle icon={FileCheck2} title="确认、修正与训练同意" detail="两个同意项相互独立，不默认勾选" /><div className="review-consent-grid"><label className="consent-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /><span><strong>确认进入健康事件</strong><small>确认后会把本次识别追加到父亲的本地健康时间线，并触发后续规则重算。</small></span></label><label className="consent-row"><input type="checkbox" checked={training} onChange={event => setTraining(event.target.checked)} /><span><strong>允许脱敏样本用于后续训练</strong><small>可选；不影响本次健康事件确认，且不会包含姓名、照片原图或报告正文。</small></span></label></div><label className="reason-field"><span>修正原因（选择修正时必填）</span><select value={reason} onChange={event => setReason(event.target.value)}><option value="">请选择</option><option>包装反光，人工补录有效期</option><option>OCR 文本与主数据冲突</option><option>其他人工核对结果</option></select></label><div className="review-actions"><a href="#视觉扫描中心" className="core-ghost-button"><X size={16} /> 返回扫描</a><button className="core-ghost-button" onClick={() => setCorrected(true)}><RotateCcw size={16} /> {corrected ? '已保存修正' : '保存修正'}</button><button className="core-primary-button" disabled={!confirmed} onClick={() => setCorrected(true)}><Check size={17} /> {confirmed ? '确认并追加事件' : '请先勾选确认'}</button></div>{corrected && <p className="success-note"><CircleCheck size={16} /> 已记录人工操作；训练同意：{training ? '已允许' : '未允许'}。</p>}</section>
  </div></PageFrame>
}

export function GraphPage() {
  const [filter, setFilter] = useState('全部')
  const [selectedNode, setSelectedNode] = useState(null)
  const nodes = [{ key: 'father', label: '父亲', type: 'member', x: 13, y: 44 }, { key: 'drug', label: '阿托伐他汀', type: 'drug', x: 42, y: 25 }, { key: 'risk', label: '血压偏高', type: 'risk', x: 73, y: 20 }, { key: 'plan', label: '晚间服用计划', type: 'plan', x: 73, y: 57 }, { key: 'report', label: '年度体检报告', type: 'report', x: 43, y: 76 }, { key: 'care', label: '张伟 · 照护者', type: 'care', x: 84, y: 82 }]
  const visible = filter === '全部' ? nodes : nodes.filter(item => item.type === filter)
  return <PageFrame title="家庭健康图谱"><div className="core-page graph-page">
    <PageIntro eyebrow="P0 · 可重建关系投影" title="家庭健康图谱" description="只展示由已确认健康事件生成的节点和关系；未确认、冲突和未知候选不会进入正式图谱。" actions={<><StatusBadge tone="good">投影已同步</StatusBadge><button className="core-outline-button"><RotateCcw size={16} /> 重建投影</button></>} />
    <div className="graph-stats"><MetricTile icon={Network} label="已确认节点" value="18" detail="较上次 +2" /><MetricTile icon={Link2} label="关系边" value="26" detail="全部可追溯" tone="lilac" /><MetricTile icon={Clock3} label="最后更新" value="刚刚" detail="事件序号 #1842" tone="peach" /><MetricTile icon={LockKeyhole} label="可见范围" value="当前家庭" detail="字段授权生效" tone="navy" /></div>
    <section className="core-surface graph-surface"><div className="graph-toolbar"><SectionTitle icon={Network} title="已确认关系投影" detail="点击节点查看来源事件与授权范围" /><div className="graph-filters">{[['全部','全部'],['member','成员'],['drug','药品'],['risk','风险'],['plan','计划']].map(([value,label]) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{label}</button>)}</div></div><div className="graph-canvas"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path d="M16 48 C28 40 30 29 43 28 S64 20 74 24" /><path d="M17 50 C30 57 31 70 44 76 S65 82 84 83" /><path d="M45 29 C55 38 64 46 74 59" /><path d="M76 25 C80 38 77 49 75 58" /><path d="M74 60 C78 66 81 74 84 82" /></svg>{visible.map(node => <button key={node.key} className={`graph-node ${node.type}`} style={{ left: `${node.x}%`, top: `${node.y}%` }} onClick={() => setSelectedNode(node)} aria-label={`查看${node.label}来源`}><span>{node.type === 'member' ? <UsersRound size={18} /> : node.type === 'drug' ? <Activity size={18} /> : node.type === 'risk' ? <ShieldAlert size={18} /> : node.type === 'plan' ? <CalendarDays size={18} /> : node.type === 'report' ? <FileText size={18} /> : <UserCheck size={18} />}</span><strong>{node.label}</strong><small>{node.type === 'member' ? '成员' : node.type === 'drug' ? '药品' : node.type === 'risk' ? '规则结果' : node.type === 'plan' ? '提醒策略' : node.type === 'report' ? '文档' : '照护关系'}</small></button>)}</div><div className="graph-legend"><span><i className="member" />成员</span><span><i className="drug" />药品</span><span><i className="risk" />风险</span><span><i className="plan" />计划</span><span><i className="report" />文档</span></div></section>
    <div className="core-two-column graph-bottom"><section className="core-surface"><SectionTitle icon={FileSearch} title="来源事件" detail="每条边都能回到事实来源" /><div className="source-event-row"><span className="source-event-dot good"><CheckCircle2 size={15} /></span><div><strong>新增药品 · 阿托伐他汀钙片</strong><small>父亲 · 已确认 · 2026-08-11 08:30</small></div><ArrowUpRight size={16} /></div><div className="source-event-row"><span className="source-event-dot info"><FileText size={15} /></span><div><strong>年度体检报告 · 3 项指标更新</strong><small>母亲 · 已解析 · 2026-08-10 14:00</small></div><ArrowUpRight size={16} /></div></section><section className="core-surface"><SectionTitle icon={ShieldCheck} title="投影安全边界" detail="页面级数据保护" /><div className="privacy-callout"><LockKeyhole size={20} /><p>撤权、补偿更正或投影不可用时，受影响节点会立即隐藏，不保留旧的敏感缓存。</p></div><a className="core-text-link" href="#权限">查看字段授权 <ArrowRight size={15} /></a></section></div>
    <ArtModal open={Boolean(selectedNode)} onClose={() => setSelectedNode(null)} icon={Network} accent={selectedNode?.type === 'risk' ? 'peach' : selectedNode?.type === 'care' ? 'mint' : 'blue'} eyebrow="已确认关系 · 来源可追溯" title={selectedNode?.label || '关系节点'} description={selectedNode ? `${selectedNode.type === 'member' ? '家庭成员' : selectedNode.type === 'drug' ? '药品实体' : selectedNode.type === 'risk' ? '规则结果' : selectedNode.type === 'plan' ? '提醒策略' : selectedNode.type === 'report' ? '健康文档' : '照护关系'} · 字段授权范围内可见` : ''}>
      {selectedNode && <><div className="art-modal-note"><FileSearch size={16} /><span>该节点由已确认健康事件生成，点击下方入口可回到对应证据来源。</span></div><div className="art-modal-list"><div className="art-modal-list-row"><div><strong>来源状态</strong><small>已确认 · 可追溯 · 事件序号 #1842</small></div><StatusBadge tone="good">已确认</StatusBadge></div><div className="art-modal-list-row"><div><strong>可见范围</strong><small>当前家庭 · 仅展示已授权字段</small></div><StatusBadge tone="navy">当前家庭</StatusBadge></div></div></>}
    </ArtModal>
  </div></PageFrame>
}

export function SafetyCenterPage() {
  const [member, setMember] = useState('父亲')
  const [expanded, setExpanded] = useState(true)
  return <PageFrame title="用药安全中心"><div className="core-page safety-page">
    <PageIntro eyebrow="P0 · 确定性规则与证据" title="用药安全中心" description="风险等级由规则决定，助手只负责解释。这里的提示不是诊断，也不替你决定停药、换药或改变剂量。" actions={<><StatusBadge tone="good">规则引擎在线</StatusBadge><a className="core-outline-button" href="#模型实验室"><ServerCog size={16} /> 规则 v1.3</a></>} />
    <div className="member-tabs core-tabs">{members.map(item => <button key={item} className={member === item ? 'active' : ''} onClick={() => setMember(item)}>{item}</button>)}</div><div className="core-two-column safety-layout"><div className="core-stack"><section className="core-surface risk-hero-card"><div className="risk-hero-head"><div><StatusBadge tone="high">HIGH · 需要确认</StatusBadge><h2>潜在药物相互作用</h2><p>{member} · 触发于今天 08:31 · 当前状态：待照护者处理</p></div><div className="risk-score">高</div></div><div className="risk-next-step"><div><span>下一步</span><strong>查看已确认事实与规则依据</strong></div><button onClick={() => setExpanded(!expanded)}>{expanded ? '收起依据' : '展开依据'} <ChevronRight size={15} /></button></div></section>{expanded && <section className="core-surface risk-evidence-card"><SectionTitle icon={FileCheck2} title="证据链与处理记录" detail="内容按当前授权范围过滤" /><div className="risk-evidence-grid"><article><span className="step-number">01</span><div><strong>已确认事实</strong><p>阿托伐他汀钙片 · 10mg · 每日 1 次<br />来源：人工复核 #REV-018 · 08:31</p></div></article><article><span className="step-number">02</span><div><strong>命中规则</strong><p>RX-004 · 肝脏代谢冲突检查<br />规则版本：risk-rules v1.3</p></div></article><article><span className="step-number">03</span><div><strong>知识文档</strong><p>《老年人安全用药指南》· 第 4 版 · P.256</p></div></article><article><span className="step-number">04</span><div><strong>人工确认状态</strong><p>等待家庭照护者确认；未生成医疗结论。</p></div></article></div><div className="risk-disclaimer"><ShieldAlert size={17} /><span>发现已知资料，需要进一步确认。出现不适时请联系医生或药师。</span></div></section>}</div><aside className="core-stack"><section className="core-surface budget-card"><SectionTitle icon={Timer} title="告警预算" detail="普通提醒合并，严重告警不被压制" /><div className="budget-ring"><div><strong>7</strong><span>/ 12</span></div></div><p>今日已使用普通提醒预算</p><div className="budget-row"><span>INFO / GENERAL</span><b><i style={{ width: '58%' }} /></b></div><div className="budget-row"><span>HIGH / URGENT</span><em>独立通道</em></div></section><section className="core-surface processing-card"><SectionTitle icon={Workflow} title="处理状态" detail="风险卡生命周期" /><div className="state-steps"><span className="done"><Check size={13} /> 发现</span><span className="done"><Check size={13} /> 证据齐备</span><span className="current"><CircleAlert size={13} /> 待确认</span><span><CircleCheck size={13} /> 已处理</span></div><a className="core-text-link" href="#本地健康助手">让助手解释这张卡 <ArrowRight size={15} /></a></section></aside></div>
  </div></PageFrame>
}

export function CarePlanPage() {
  const [member, setMember] = useState('父亲')
  const [tasks, setTasks] = useState([false, true])
  const [saved, setSaved] = useState(false)
  return <PageFrame title="健康计划中心"><div className="core-page plan-page">
    <PageIntro eyebrow="P0 · 计划确认与照护升级" title="健康计划中心" description="医嘱事实只读，提醒策略可在安全时间窗内调整。任何版本变化都会保留批准人、时间和授权依据。" actions={<><StatusBadge tone="good">计划 v2.4 · 已同步</StatusBadge><button className="core-outline-button"><Layers3 size={16} /> 查看版本差异</button></>} />
    <div className="member-tabs core-tabs">{members.map(item => <button key={item} className={member === item ? 'active' : ''} onClick={() => setMember(item)}>{item}</button>)}</div><div className="plan-layout"><div className="core-stack"><section className="core-surface"><SectionTitle icon={FileCheck2} title="医嘱事实 · 只读" detail="来源于已确认健康事件，不提供直接改剂量入口" /><div className="fact-table"><div className="fact-row head"><span>药品</span><span>剂量与频次</span><span>来源</span></div><div className="fact-row"><div><strong>阿托伐他汀钙片</strong><small>已确认 · 父亲</small></div><span>10mg · 每日一次<br />晚间 20:00</span><span><FileText size={14} /> REV-018</span></div><div className="fact-row"><div><strong>二甲双胍</strong><small>已确认 · 父亲</small></div><span>500mg · 每日三次<br />随餐服用</span><span><FileText size={14} /> EVT-1809</span></div></div></section><section className="core-surface strategy-card"><SectionTitle icon={SlidersHorizontal} title="提醒策略 · 可调整" detail="只在安全时间窗内调整首次提醒、再提醒和升级对象" /><div className="strategy-row"><div><strong>首次提醒</strong><small>服用时间前 15 分钟</small></div><button className="strategy-select">19:45 <ChevronRight size={15} /></button></div><div className="strategy-row"><div><strong>再提醒</strong><small>首次提醒后 20 分钟</small></div><button className="strategy-select">20:05 <ChevronRight size={15} /></button></div><div className="strategy-row"><div><strong>升级对象</strong><small>超时后通知首要照护者</small></div><button className="strategy-select">林建国 <ChevronRight size={15} /></button></div><div className="strategy-foot"><Info size={15} /> 当前策略变更不会改变药品剂量、频次或医嘱事实。</div></section></div><aside className="core-stack"><section className="core-surface today-plan"><SectionTitle icon={CalendarDays} title="今日照护任务" detail="父亲 · 2026-08-11" /><div className="plan-progress"><div><strong>{tasks.filter(Boolean).length}</strong><span>/ 2 已完成</span></div><b><i style={{ width: `${tasks.filter(Boolean).length * 50}%` }} /></b></div><label className={`plan-task ${tasks[0] ? 'done' : ''}`}><input type="checkbox" checked={tasks[0]} onChange={() => { setTasks([!tasks[0], tasks[1]]); setSaved(false) }} /><span><strong>阿托伐他汀钙片</strong><small>20:00 · 待确认</small></span><StatusBadge tone={tasks[0] ? 'good' : 'warn'}>{tasks[0] ? '已确认' : '待处理'}</StatusBadge></label><label className={`plan-task ${tasks[1] ? 'done' : ''}`}><input type="checkbox" checked={tasks[1]} onChange={() => { setTasks([tasks[0], !tasks[1]]); setSaved(false) }} /><span><strong>血压早晚记录</strong><small>08:00 / 20:30 · 自动同步</small></span><StatusBadge tone="good">已确认</StatusBadge></label><div className="plan-actions"><button onClick={() => setSaved(true)}>延期 20 分钟</button><button className="core-primary-button" onClick={() => { setTasks([true, true]); setSaved(true) }}><Check size={15} /> 全部确认</button></div>{saved && <p className="success-note"><CircleCheck size={15} /> 已记录照护操作并写入审计。</p>}</section><section className="core-surface escalation-card"><SectionTitle icon={ShieldAlert} title="升级策略" detail="超过宽限期后自动通知" /><div><span>临近</span><strong>家庭设备提醒</strong></div><div><span>逾期</span><strong>再次提醒本人</strong></div><div><span>升级</span><strong>通知首要照护者</strong></div></section></aside></div>
  </div></PageFrame>
}

export function AssistantPage() {
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState(false)
  return <PageFrame title="本地健康助手"><div className="core-page assistant-page">
    <PageIntro eyebrow="P0 · 证据解释，不做诊疗" title="本地健康助手" description="先检索事实、规则和文档，再生成通俗解释。没有足够证据时，助手会明确拒答并给出补证据路径。" actions={<StatusBadge tone="good"><span className="pulse-dot" /> Ollama 本地模型在线</StatusBadge>} />
    <div className="assistant-context"><span><UsersRound size={15} /> 当前成员：父亲</span><span><Eye size={15} /> 可见范围：家庭健康摘要 + 已确认用药</span><span><Database size={15} /> 证据模式：强制引用</span><span><LockKeyhole size={15} /> 教学演示，不用于诊断</span></div>
    <div className="assistant-grid"><section className="core-surface assistant-chat"><div className="assistant-chat-head"><div className="assistant-avatar"><MessageCircle size={21} /></div><div><strong>家健镜本地助手</strong><small>基于当前可见事实回答 · 不出网</small></div><StatusBadge tone="good">可用</StatusBadge></div><div className="assistant-welcome"><span>你好，我会把家庭健康事实、命中规则和来源文档整理成可核对的解释。</span><div className="question-chips"><button onClick={() => setQuestion('为什么父亲最近出现新的提醒？')}>为什么提醒增加了？</button><button onClick={() => setQuestion('这张风险卡的依据是什么？')}>风险卡依据是什么？</button><button onClick={() => setQuestion('当前资料不足时怎么办？')}>资料不足怎么办？</button></div></div>{asked && <div className="assistant-answer"><div className="answer-label"><Sparkles size={15} /> 结构化回答 · 生成于刚刚</div><h3>结论摘要</h3><p>当前提醒增加与一条已确认的用药变化和一条血压规则命中有关；这不是诊断结论，需要由照护者进一步确认。</p><div className="answer-sections"><article><strong>依据事实</strong><span>阿托伐他汀钙片 · 10mg · 今日新增</span><span>近 3 天平均血压 148/92 mmHg</span></article><article><strong>命中规则</strong><span>RX-004 · 肝脏代谢冲突检查 · v1.3</span><span>BP-002 · 血压升高趋势 · v0.9</span></article><article><strong>文档引用</strong><span>《老年人安全用药指南》第 4 版 P.256</span><span>引用可回到原始证据和确认记录</span></article><article><strong>照护动作</strong><span>查看风险卡并完成确认；如出现不适，联系医生或药师。</span></article></div><div className="answer-boundary"><ShieldAlert size={16} /> 助手不能诊断、开方、停药、换药或判断剂量。</div></div>}<form className="assistant-composer" onSubmit={event => { event.preventDefault(); if (question.trim()) setAsked(true) }}><input value={question} onChange={event => setQuestion(event.target.value)} placeholder="例如：为什么父亲最近提醒增加了？" /><button type="submit"><ArrowRight size={18} /></button></form></section><aside className="core-stack"><section className="core-surface evidence-mode"><SectionTitle icon={FileSearch} title="当前证据上下文" detail="回答前先检索" /><div className="evidence-context-row"><span>已确认事件</span><strong>12 条</strong></div><div className="evidence-context-row"><span>可用规则</span><strong>8 条</strong></div><div className="evidence-context-row"><span>已引用文档</span><strong>3 份</strong></div><div className="evidence-context-row muted"><span>未获授权字段</span><strong>已隐藏</strong></div></section><section className="core-surface assistant-empty"><Cloud size={23} /><h3>资料不足时怎么办？</h3><p>助手会保留事实卡，但不会用猜测补齐医疗结论。你可以补充照片、查看原始记录，或将提示交给医生/药师。</p><a className="core-text-link" href="#添加健康事件">补充一条证据 <ArrowRight size={15} /></a></section></aside></div>
  </div></PageFrame>
}

export function BigScreenPage() {
  const views = ['今日任务', '近期变化', '告警预算', '照护响应', '本地运行状态']
  const [view, setView] = useState(views[0])
  return <PageFrame title="家庭健康大屏"><div className="core-page big-screen-page">
    <PageIntro eyebrow="P0 · 公共可见聚合" title="家庭健康大屏" description="面向家庭共同查看的非敏感聚合视图。成员姓名、病史、药品详情和对话正文不会默认出现在这里。" actions={<><StatusBadge tone="good"><span className="pulse-dot" /> 家庭模式</StatusBadge><button className="core-outline-button"><Eye size={16} /> 预览公共视图</button></>} />
    <div className="big-screen-tabs">{views.map(item => <button key={item} className={view === item ? 'active' : ''} onClick={() => setView(item)}>{item}</button>)}</div><div className="big-screen-hero"><div><StatusBadge tone="good">本地运行正常</StatusBadge><h2>{view === '今日任务' ? '今天，照护节奏清晰可见' : view === '近期变化' ? '最近变化都能回到来源' : view === '告警预算' ? '提醒有节制，严重事项不漏掉' : view === '照护响应' ? '家庭响应正在被记录' : '家庭可信域运行状态'}</h2><p>{view === '今日任务' ? '只显示任务数量与处理状态，敏感详情需要进入获权成员视图。' : '当前大屏只展示经过授权和脱敏的聚合指标。'}</p></div><div className="big-screen-visual"><div className="orbit-ring ring-one" /><div className="orbit-ring ring-two" /><div className="orbit-core"><HeartPulse size={31} /></div></div></div><div className="big-screen-metrics"><MetricTile icon={ClipboardCheck} label="待处理任务" value="03" detail="其中高风险 1 项" tone="navy" /><MetricTile icon={Activity} label="过去 7 天变化" value="12" detail="已确认事件" tone="blue" /><MetricTile icon={ShieldCheck} label="本地处理率" value="100%" detail="健康数据不出网" tone="lilac" /><MetricTile icon={UsersRound} label="照护响应" value="86%" detail="平均 18 分钟" tone="peach" /></div><div className="big-screen-bottom"><section className="core-surface screen-list"><SectionTitle icon={Activity} title="脱敏活动流" detail="只显示事件类型、状态和时间" /><div className="screen-event"><span className="screen-event-icon good"><CheckCircle2 size={17} /></span><div><strong>健康事件已确认</strong><small>刚刚 · 来源可追溯</small></div><StatusBadge tone="good">已完成</StatusBadge></div><div className="screen-event"><span className="screen-event-icon warn"><AlertTriangle size={17} /></span><div><strong>高风险事项待处理</strong><small>12 分钟前 · 需要照护者</small></div><StatusBadge tone="warn">待处理</StatusBadge></div><div className="screen-event"><span className="screen-event-icon info"><Cloud size={17} /></span><div><strong>本地同步完成</strong><small>今天 08:30 · 设备状态正常</small></div><StatusBadge tone="good">正常</StatusBadge></div></section><section className="core-surface screen-safety"><SectionTitle icon={LockKeyhole} title="公共模式边界" detail="大屏不暴露敏感正文" /><div><Check size={15} /> 不显示病史、报告正文和药品详情</div><div><Check size={15} /> 未确认数据不进入趋势和排名</div><div><Check size={15} /> 权限撤销后聚合立即隐藏</div><a className="core-text-link" href="#权限">查看授权摘要 <ArrowRight size={15} /></a></section></div>
  </div></PageFrame>
}

const modelLabRecords = [
  {
    id: 'hct-yolo11n-box-assist-experimental-v1.3',
    status: 'EXPERIMENTAL_UNRELEASED',
    registeredAt: '2026-08-11 22:04',
    code: ['未登记', 'original_code_commit=null'],
    data: ['HCT-201-dataset-v1.2-annotation-reviewed-candidate', 'a0ffc701…e52d312'],
    model: ['YOLO11n · 50 epoch · seed 42', 'fcda34dd…7a35f92'],
    prompt: ['不适用', '仅包装区域建议'],
    knowledge: ['不适用', '不读取家庭知识'],
    rules: ['发布门禁', '家庭运行禁止加载'],
    metric: 'P=0.9864 · R=1.0000 · mAP50-95=0.9284 · CPU P95=137.319ms',
    limitation: '候选 test 147 张；不是获批固定集。2/2 困难负样本在阈值 ≤0.75 时误检。',
  },
  {
    id: 'hct-yolo11n-box-assist-experimental-v1.2',
    status: 'EXPERIMENTAL_UNRELEASED',
    registeredAt: '2026-08-11 00:00',
    code: ['未登记', 'original_code_commit=null'],
    data: ['HCT-201-dataset-v1.2-annotation-reviewed-candidate', 'a0ffc701…e52d312'],
    model: ['YOLO11n · 50 epoch · seed 42', 'cedb5b52…5a7d1b'],
    prompt: ['不适用', '仅包装区域建议'],
    knowledge: ['不适用', '不读取家庭知识'],
    rules: ['发布门禁', '家庭运行禁止加载'],
    metric: 'P=0.9864 · R=1.0000 · mAP50-95=0.9273 · CPU P95=111.592ms',
    limitation: '候选 test 147 张；不是获批固定集。2/2 困难负样本在阈值 0.25 时误检。',
  },
]

const rollbackInitialState = {
  status: 'IDLE',
  requestId: '',
  target: 'vision_model_version=unavailable',
  message: '尚未执行教学回滚演练；家庭运行时事实仍为 unavailable。',
  audit: [],
}

function readRollbackDemoState() {
  try {
    return JSON.parse(window.localStorage.getItem('hct407-rollback-demo-v1')) || rollbackInitialState
  } catch {
    return rollbackInitialState
  }
}

function ArtifactCell({ value }) {
  return <span className="artifact-cell"><strong>{value[0]}</strong><small>{value[1]}</small></span>
}

function ModelLabState({ mode, onReset }) {
  const states = {
    empty: [Database, '暂无已登记实验', '当前筛选没有登记记录；不会加载真实家庭数据或模型权重。'],
    error: [CircleAlert, '登记校验失败', '无法校验模型卡和登记哈希。页面保持只读，家庭运行时继续使用 unavailable。'],
    offline: [Cloud, '离线只读', '显示本地登记摘要；发布和回滚演练入口已停用，禁止云端回退。'],
    unauthorized: [LockKeyhole, '无模型管理员权限', '非管理员不能查看指标详情、样本摘要或执行回滚演练。'],
  }
  const [Icon, title, detail] = states[mode]
  return <section className="core-surface lab-state-panel"><Icon size={30} /><h2>{title}</h2><p>{detail}</p><button className="core-outline-button" onClick={onReset}>恢复正常演示</button></section>
}

export function ModelLabPage() {
  const [view, setView] = useState('registry')
  const [pageState, setPageState] = useState(() => navigator.onLine ? 'normal' : 'offline')
  const [rollbackState, setRollbackState] = useState(readRollbackDemoState)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [permissionConfirmed, setPermissionConfirmed] = useState(false)
  const [confirmText, setConfirmText] = useState('')

  useEffect(() => {
    try { window.localStorage.setItem('hct407-rollback-demo-v1', JSON.stringify(rollbackState)) } catch { /* 受限浏览器仅保留当前会话 */ }
  }, [rollbackState])

  useEffect(() => {
    const online = () => setPageState('normal')
    const offline = () => setPageState('offline')
    window.addEventListener('online', online)
    window.addEventListener('offline', offline)
    return () => {
      window.removeEventListener('online', online)
      window.removeEventListener('offline', offline)
    }
  }, [])

  const openRollbackDemo = () => {
    setPermissionConfirmed(false)
    setConfirmText('')
    setConfirmOpen(true)
  }

  const executeRollbackDemo = () => {
    if (!permissionConfirmed || confirmText !== 'ROLLBACK') return
    const requestId = 'DEMO-RB-vision-unavailable'
    if (rollbackState.requestId === requestId) {
      setRollbackState(current => ({ ...current, message: '检测到相同请求 ID，重复演练已幂等忽略，未追加第二条审计。' }))
    } else {
      setRollbackState({
        status: 'DEMO_COMPLETED',
        requestId,
        target: 'vision_model_version=unavailable',
        message: '教学演练已完成并在浏览器本地恢复；未调用后端、未切换真实运行时。',
        audit: [{ id: 'DEMO-AUD-001', actor: 'synthetic-release-admin', action: '回滚演练', result: 'DEMO_ONLY' }],
      })
    }
    setConfirmOpen(false)
  }

  return <PageFrame title="模型实验室"><div className="core-page model-page">
    <PageIntro eyebrow="P0 · 管理员 / 研发教学演示" title="模型实验室" description="只展示仓库中的实验登记、模型卡指标和合成状态。页面不接真实 API、不加载权重，也不能执行真实发布或回滚。" actions={<StatusBadge tone="navy"><LockKeyhole size={13} /> SYNTHETIC DEMO</StatusBadge>} />

    <div className="model-lab-tabs" role="tablist" aria-label="模型实验室视图">
      {[['registry', '版本登记'], ['metrics', '版本指标'], ['rollback', '回滚状态']].map(([key, label]) => <button role="tab" aria-selected={view === key} className={view === key ? 'active' : ''} key={key} onClick={() => setView(key)}>{label}</button>)}
      <label>状态演练<select aria-label="状态演练" value={pageState} onChange={event => setPageState(event.target.value)}><option value="normal">正常</option><option value="empty">空状态</option><option value="error">错误</option><option value="offline">离线</option><option value="unauthorized">未授权</option></select></label>
    </div>

    {pageState !== 'normal' ? <ModelLabState mode={pageState} onReset={() => setPageState('normal')} /> : <>
      <div className="model-alert"><ServerCog size={20} /><div><strong>家庭运行门禁：当前没有 APPROVED 模型</strong><p>两个登记均为 EXPERIMENTAL_UNRELEASED；家庭运行时保持 vision_model_version=unavailable。</p></div><StatusBadge tone="warn">发布阻塞</StatusBadge></div>

      {view === 'registry' && <>
        <div className="model-status-legend" aria-label="发布状态说明">
          <span><i className="experimental" /><b>实验</b> 当前 2</span><span><i className="candidate" /><b>候选</b> 当前 0</span><span><i className="approved" /><b>已批准</b> 当前 0</span><span><i className="rolled-back" /><b>已回滚</b> 当前 0</span>
        </div>
        <div className="model-metrics"><MetricTile icon={Layers3} label="实验登记" value="02" detail="均禁止家庭加载" /><MetricTile icon={ShieldCheck} label="已批准" value="00" detail="运行时 unavailable" tone="navy" /><MetricTile icon={Database} label="真实家庭样本" value="0" detail="页面绝不加载" tone="lilac" /><MetricTile icon={Cloud} label="云端回退" value="关闭" detail="本地默认不出网" tone="peach" /></div>
        <section className="core-surface model-registry"><SectionTitle icon={Layers3} title="组合版本登记" detail="事实源：HCT-203 模型卡与机器可读登记；缺失项明确显示“未登记/不适用”" />
          <div className="registry-scroll"><div className="registry-table">
            <div className="registry-row head"><span>模型 / 状态</span><span>代码</span><span>数据</span><span>模型</span><span>提示词</span><span>知识</span><span>规则</span></div>
            {modelLabRecords.map(record => <article className="registry-row" key={record.id}>
              <div><StatusBadge tone="warn">实验</StatusBadge><strong>{record.id}</strong><small>CONTROLLED_TRAINING_MACHINE<br />{record.registeredAt}</small></div>
              <ArtifactCell value={record.code} /><ArtifactCell value={record.data} /><ArtifactCell value={record.model} /><ArtifactCell value={record.prompt} /><ArtifactCell value={record.knowledge} /><ArtifactCell value={record.rules} />
              <footer><span><b>指标：</b>{record.metric}</span><span><b>限制：</b>{record.limitation}</span><button disabled><LockKeyhole size={14} /> 未批准，禁止调用</button></footer>
            </article>)}
          </div></div>
        </section>
      </>}

      {view === 'metrics' && <>
        <section className="benchmark-banner"><GitCompareArrows size={20} /><div><strong>同一候选 test 输入集 · 不是获批固定集</strong><p>147 张、145 个真值实例 · 输入 SHA-256 eeca28b6…2eae · confidence 0.25。指标只能描述实验。</p></div><StatusBadge tone="warn">不可发布</StatusBadge></section>
        <div className="model-metrics"><MetricTile icon={Gauge} label="v1.3 mAP50-95" value="0.9284" detail="v1.2 为 0.9273" /><MetricTile icon={ScanSearch} label="v1.3 Recall" value="1.0000" detail="候选 test 结果" tone="lilac" /><MetricTile icon={Zap} label="v1.3 CPU P95" value="137.319ms" detail="仅 YOLO 组件" tone="peach" /><MetricTile icon={ShieldAlert} label="困难负样本误检" value="2 / 2" detail="阈值 ≤ 0.75" tone="navy" /></div>
        <div className="model-metric-layout">
          <section className="core-surface metric-comparison"><SectionTitle icon={GitCompareArrows} title="同口径 V1.2 / V1.3" detail="不只展示最好分数；延迟退化和误检同时保留" /><div className="metric-table"><div className="metric-row head"><span>指标</span><span>V1.2</span><span>V1.3</span><span>说明</span></div>{[
            ['Precision', '0.9864', '0.9864', '候选 test'],
            ['Recall', '1.0000', '1.0000', '候选 test'],
            ['mAP@0.5:0.95', '0.9273', '0.9284', '+0.0011'],
            ['CPU P95', '111.592ms', '137.319ms', '变慢 25.727ms'],
            ['困难负样本', '2/2 误检', '2/2 误检', '阻塞发布'],
          ].map((row, index) => <div className={`metric-row ${index >= 3 ? 'failed' : ''}`} key={row[0]}>{row.map(value => <span key={value}>{value}</span>)}</div>)}</div></section>
          <section className="core-surface failure-categories"><SectionTitle icon={ShieldAlert} title="失败类别与安全边界" detail="不展示原图或健康正文" /><div className="failure-category"><span>非纸盒泡罩包装误检</span><b className="danger">1</b><small>v1.3 置信度 0.8585</small></div><div className="failure-category"><span>非纸盒输液袋误检</span><b className="danger">1</b><small>v1.3 置信度 0.8461</small></div><div className="failure-category"><span>原始训练代码未跟踪</span><b>1</b><small>PARTIAL_UNTRACKED_ORIGINAL_CODE</small></div><div className="failure-category"><span>获批 fixed / unknown 集</span><b>0</b><small>发布阻断</small></div></section>
        </div>
      </>}

      {view === 'rollback' && <div className="rollback-layout">
        <div className="core-stack">
          <section className="core-surface rollback-runtime"><SectionTitle icon={ServerCog} title="家庭运行时事实" detail="来自 HCT-203 v1.3 登记" /><div className="runtime-version"><StatusBadge tone="muted">UNAVAILABLE</StatusBadge><div><strong>vision_model_version=unavailable</strong><small>没有 APPROVED 模型，家庭端不得加载实验权重</small></div></div><div className="runtime-guard"><LockKeyhole size={18} /><div><strong>实验与生产隔离</strong><p>本页只有前端演练状态；真实权限、幂等、审计和原子切换必须由后端权威状态机提供。</p></div></div></section>
          <section className="core-surface rollback-targets"><SectionTitle icon={RotateCcw} title="回滚教学演练" detail="不调用 API，不修改模型、规则或医疗事实" /><div className="rollback-target"><div><strong>目标：vision_model_version=unavailable</strong><small>稳定请求 ID · 二次确认 · 浏览器本地恢复</small></div><button className="core-outline-button" onClick={openRollbackDemo}><RotateCcw size={14} /> 开始演练</button></div></section>
        </div>
        <aside className="core-stack">
          <section className="core-surface rollback-state"><SectionTitle icon={Workflow} title="演练状态机" detail={`请求 ${rollbackState.requestId || '—'}`} /><div className="rollback-steps"><span className={rollbackState.status === 'DEMO_COMPLETED' ? 'done' : ''}><Check size={13} /> 权限声明</span><span className={rollbackState.status === 'DEMO_COMPLETED' ? 'done' : ''}><Check size={13} /> 二次确认</span><span className={rollbackState.status === 'DEMO_COMPLETED' ? 'done' : ''}><Check size={13} /> 幂等处理</span><span className={rollbackState.status === 'DEMO_COMPLETED' ? 'done' : ''}><Check size={13} /> 本地恢复</span></div><p className="rollback-message">{rollbackState.message}</p><small>该状态仅用于 Playwright 验收，不能作为真实生产审计证据。</small></section>
          <section className="core-surface audit-panel"><SectionTitle icon={FileCheck2} title="演练审计" detail="刷新页面后从 localStorage 恢复" />{rollbackState.audit.length ? rollbackState.audit.map(item => <article key={item.id}><div><strong>{item.action}</strong><small>{item.actor}</small></div><StatusBadge tone="muted">{item.result}</StatusBadge><p>{item.id} · {rollbackState.target}</p></article>) : <p className="version-muted">暂无演练记录</p>}</section>
        </aside>
      </div>}
    </>}

    {confirmOpen && <div className="rollback-dialog-backdrop" role="presentation"><section className="rollback-dialog" role="dialog" aria-modal="true" aria-labelledby="rollback-title">
      <div className="rollback-dialog-icon"><ShieldAlert size={24} /></div><h2 id="rollback-title">二次确认回滚演练</h2><p>目标为 <b>vision_model_version=unavailable</b>。本操作仅写入浏览器本地演练状态，不会调用后端或改变家庭运行时。</p>
      <label className="rollback-permission"><input type="checkbox" checked={permissionConfirmed} onChange={event => setPermissionConfirmed(event.target.checked)} />我确认这是合成教学演练，并声明具备 RELEASE_ROLLBACK 演示权限</label>
      <label className="rollback-confirm-input"><span>输入 ROLLBACK 完成二次确认</span><input value={confirmText} onChange={event => setConfirmText(event.target.value)} placeholder="ROLLBACK" autoComplete="off" /></label>
      <div className="rollback-dialog-actions"><button className="core-ghost-button" onClick={() => setConfirmOpen(false)}>取消</button><button className="core-primary-button" disabled={!permissionConfirmed || confirmText !== 'ROLLBACK'} onClick={executeRollbackDemo}><RotateCcw size={15} /> 执行幂等演练</button></div>
    </section></div>}
  </div></PageFrame>
}
