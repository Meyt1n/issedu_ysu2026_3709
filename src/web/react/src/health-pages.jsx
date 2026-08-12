import { useRef, useState } from 'react'
import { Activity, ArrowLeft, Camera, CheckCircle2, ClipboardPenLine, Download, FilePlus2, FileText, Grid2X2, HeartPulse, List, Plus, ScanLine, Sparkles, Upload, UsersRound } from 'lucide-react'
import { PageFrame } from './template-pages.jsx'
import { FamilyAvatar } from './avatar-system.jsx'

const members = ['父亲', '母亲', '我', '孩子']
const memberAvatarKeys = { 父亲: 'father', 母亲: 'mother', 我: 'self', 孩子: 'child' }
const reports = [
  ['2024年4月12日', '2024年度常规体检报告', '北京协和医院', '整体健康状况良好。发现 3项指标偏高（血压、甘油三酯、尿…）'],
  ['2023年10月05日', '心血管专项检查报告', '中国人民解放军总医院', '心电图显示轻度心律不齐。1项指标异常（低密度脂蛋白胆固醇偏…）'],
  ['2023年4月20日', '2023年度常规体检报告', '北京协和医院', '各项基本指标稳定。4项指标偏高，相比上一年增加1项异常，…'],
]

export function ReportsPage() {
  const [member, setMember] = useState('父亲')
  const [grid, setGrid] = useState(true)
  const uploadRef = useRef(null)
  return <PageFrame title="健康报告"><div className="reports-top"><div><p className="eyebrow">历史数据与趋势</p><h1>健康报告中心</h1></div><button className="upload-report" onClick={() => uploadRef.current?.click()}><Upload size={18} /> 上传新报告</button><input ref={uploadRef} className="visually-hidden" type="file" accept=".pdf,image/*" /></div><div className="member-tabs">{members.map(item => <button key={item} className={member === item ? 'active' : ''} onClick={() => setMember(item)}><FamilyAvatar memberKey={memberAvatarKeys[item]} name={item} className="tab-avatar" />{item}</button>)}</div><div className="reports-overview"><section className="trend-panel"><div className="trend-head"><div><h2><Activity size={21} /> 核心指标趋势 ({member})</h2><p>最近5次体检报告数据追踪</p></div><span><i className="red" /> 血压 <i className="blue" /> 空腹血糖</span></div><div className="bar-chart"><div className="chart-line" /><div className="chart-line" /><div className="chart-line" />{[['64','46','2022'],['78','52','2023上'],['95','59','2023下'],['72','65','2024上'],['55','47','最新']].map(([red, blue, label]) => <div className="bar-group" key={label}><div className="bars"><b style={{ height: `${red}%` }} /><b style={{ height: `${blue}%` }} /></div><span>{label}</span></div>)}</div></section><aside className="abnormal-panel"><h2><FileText size={22} /> 异常指标统计</h2><p>基于所有已解析报告</p><div className="abnormal-count">12</div><div className="abnormal-copy"><b>项偏高/偏低</b><span>较去年同期下降3项 ↓</span></div><div className="abnormal-foot"><strong>最高频异常</strong><div><span>血压偏高 (4次)</span><span>低密度脂蛋白 (3次)</span></div></div></aside></div><div className="reports-list-head"><h2>历史报告列表</h2><div><a className="compare-report-link" href="#报告对比">对比报告</a></div></div><div className={grid ? 'report-grid' : 'report-list'}>{reports.map(([date, title, hospital, summary], index) => <article className="report-card" key={title}><div className="report-card-head"><span>{date}</span><b><CheckCircle2 size={14} /> 已解析</b></div><h3>{title}</h3><p className="hospital"><FilePlus2 size={16} /> {hospital}</p><div className="report-summary"><strong>AI 摘要：</strong><p>{summary}</p></div><div className="report-actions"><button><Download size={17} /> 下载PDF</button><button className="detail-static">查看详情 →</button></div></article>)}</div></PageFrame>
}

const eventTypes = [['药品拍照识别', Camera], ['上传体检报告', Upload], ['手动记录指标', ClipboardPenLine]]

export function AddHealthEventPage() {
  const [type, setType] = useState(0)
  const [member, setMember] = useState('父亲 (Father)')
  const [fileName, setFileName] = useState('')
  const [saved, setSaved] = useState(false)
  const [metric, setMetric] = useState('血压')
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('mmHg')
  const [note, setNote] = useState('')
  const fileRef = useRef(null)
  const chooseMetric = (name, nextUnit) => { setMetric(name); setUnit(nextUnit); setSaved(false) }
  return <PageFrame title="添加健康事件"><div className="event-page-head"><a href="#控制面板"><ArrowLeft size={22} /></a><div><p className="eyebrow">本地 AI 处理</p><h1>添加健康事件</h1></div><span>本地AI解析中，数据不离开您的设备</span></div><div className="event-layout"><div className="event-main"><section className="event-surface"><h2><ScanLine size={22} /> 选择事件类型</h2><div className="event-type-grid three-types">{eventTypes.map(([label, Icon], index) => <button key={label} className={type === index ? 'active' : ''} onClick={() => { setType(index); setSaved(false) }}><Icon size={29} /><span>{label}</span></button>)}</div></section>{type === 2 ? <section className="event-surface manual-metric-surface"><div className="manual-heading"><div><h2><ClipboardPenLine size={22} /> 手动记录指标</h2><p>将本次测量结果保存到本地健康档案。</p></div><span>本地记录</span></div><div className="metric-choice-row">{[['血压','mmHg'],['血糖','mmol/L'],['心率','bpm'],['体温','°C'],['自定义','']].map(([name, nextUnit]) => <button className={metric === name ? 'selected' : ''} onClick={() => chooseMetric(name, nextUnit)} key={name}>{name}</button>)}</div><div className="manual-form-grid"><label><span>指标名称</span><input value={metric} onChange={event => setMetric(event.target.value)} placeholder="例如：血压" /></label><label><span>测量数值</span><input value={value} onChange={event => { setValue(event.target.value); setSaved(false) }} inputMode="decimal" placeholder="请输入数值" /></label><label><span>单位</span><input value={unit} onChange={event => setUnit(event.target.value)} placeholder="例如：mmHg" /></label><label><span>记录时间</span><input type="datetime-local" defaultValue="2026-08-11T09:30" /></label><label className="manual-note"><span>备注（可选）</span><textarea value={note} onChange={event => setNote(event.target.value)} placeholder="添加症状、测量状态或其他说明" /></label></div><div className="manual-tip"><HeartPulse size={17} /><span>保存后会作为新的健康事件同步至家庭成员档案。</span></div></section> : <section className="event-surface upload-surface"><h2><Sparkles size={22} /> 智能提取区</h2><div className="upload-drop" onClick={() => fileRef.current?.click()}><span><Camera size={31} /></span><h3>{fileName || '点击拍照或拖拽图片至此'}</h3><p>支持识别药盒包装、处方单、化验单等。边缘AI将自动提取关键信息。</p><button type="button">浏览文件</button><input ref={fileRef} className="visually-hidden" type="file" accept="image/*,.pdf" onChange={event => setFileName(event.target.files?.[0]?.name || '')} /></div></section>}</div><aside className="event-side"><section className="event-surface member-select"><h2><UsersRound size={22} /> 归属成员</h2>{['父亲 (Father)', '母亲 (Mother)'].map(item => { const memberKey = item.startsWith('父亲') ? '父亲' : '母亲'; return <button key={item} className={member === item ? 'selected' : ''} onClick={() => setMember(item)}><span className="radio" /><FamilyAvatar memberKey={memberAvatarKeys[memberKey]} name={memberKey} className="event-member-avatar" />{item}</button> })}</section><section className="event-submit"><button onClick={() => setSaved(true)}><Sparkles size={19} /> {type === 2 ? '保存指标记录' : '开始解析/保存'}</button><a href="#控制面板">取消</a>{saved && <p><CheckCircle2 size={15} /> {type === 2 && value ? `${metric} ${value}${unit ? ` ${unit}` : ''} 已` : '已'}为{member}保存健康事件</p>}</section></aside></div></PageFrame>
}


export function ReportComparisonPage() {
  const rows = [
    ['空腹血糖', '7.2 mmol/L ↑', '3.9 - 6.1', '6.5', 'high'],
    ['血压', '135/85 mmHg ↑', '< 120/80', '128/82', 'high'],
    ['总胆固醇', '4.5 mmol/L', '< 5.18', '4.8', 'normal'],
    ['谷丙转氨酶 (肝功能)', '25 U/L', '9 - 50', '22', 'normal'],
    ['维生素 D', '15 ng/mL ↓', '20 - 50', '18', 'low'],
  ]
  return <PageFrame title="健康报告"><div className="compare-breadcrumb"><a href="#健康报告">报告</a><span>›</span><b>体检报告结构化解析</b></div><div className="compare-head"><div><h1>体检报告对比视图</h1><p>▣ 2024-05-15　⌑ XX国际体检中心　♙ 父亲</p></div><div><button><Download size={17} /> 下载 PDF</button><button className="consult-button"><HeartPulse size={17} /> 查看医疗边界</button></div></div><div className="compare-layout"><aside className="compare-sidebar"><div className="compare-stat"><span>指标总数</span><strong>32</strong></div><div className="compare-stat danger"><span>异常项</span><strong>3 <Activity size={24} /></strong></div><section className="compare-risk"><h2><Activity size={23} /> 核心风险提示</h2><article><b>↑</b><div><strong>空腹血糖</strong><p>近2年持续偏高</p></div></article><article><b>↑</b><div><strong>收缩压</strong><p>处于一级高血压临界点</p></div></article></section><section className="compare-ai"><h2><Sparkles size={23} /> 证据摘要</h2><p>血糖较去年（2023-05-10）上升了 15%，这是基于报告数据的趋势摘要，不代表诊断或治疗建议。需要进一步判断时，请把原始报告交给医生或药师核对。</p></section></aside><section className="comparison-table"><div className="comparison-table-head"><h2>指标对比详情</h2><div><span className="dot high" /> 偏高 <span className="dot low" /> 偏低 <span className="dot normal" /> 正常</div></div><div className="compare-table-scroll"><table><thead><tr><th>检测项目</th><th>当前数值<br />(24/05/15)</th><th>参考区间</th><th>历史数值<br />(23/05/10)</th><th>变化趋势</th></tr></thead><tbody>{rows.map(([item, now, ref, old, tone]) => <tr className={tone} key={item}><td>{item}</td><td>{now}</td><td>{ref}</td><td>{old}</td><td><span className="mini-trend"><i /><b className={tone} /></span></td></tr>)}</tbody></table></div></section></div></PageFrame>
}



