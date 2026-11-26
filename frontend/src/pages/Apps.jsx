import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Apps() {
  const [rows, setRows] = useState([])
  const [roster, setRoster] = useState([])
  const [stamp, setStamp] = useState(null)
  const [gap, setGap] = useState(null)
  const [name, setName] = useState('')
  const [owner, setOwner] = useState('')
  const [err, setErr] = useState('')
  const load = async () => {
    const [apps, r] = await Promise.all([api('/应用'), api('/应用名册')])
    setRows(apps)
    setRoster(r.名册 || [])
    setStamp(r.投影 || null)
    setGap(r.投影缺口 || null)
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])
  const create = async () => {
    setErr('')
    try {
      await api('/应用', { method: 'POST', body: JSON.stringify({ 名称: name, 负责人: owner, 状态: '启用' }) })
      setName(''); setOwner(''); load()
    } catch (e) { setErr(e.message) }
  }
  // 名册三环境列：按应用聚合，环境顺序由后端 sort_order 保证
  const byApp = {}
  for (const r of roster) {
    if (!byApp[r.应用编号]) byApp[r.应用编号] = { 名称: r.应用, 列: {} }
    byApp[r.应用编号].列[r.环境] = r
  }
  const envOrder = [...new Set(roster.map((r) => r.环境))]
  return (
    <div className="panel">
      <h2>应用名册</h2>
      {err && <p className="err">{err}</p>}
      {stamp && (
        <p className="muted">
          名册版本由事件重投影维护 · 投影任务号 {stamp.投影任务号} · 版本/刷新戳 {stamp.刷新戳 || '-'}
        </p>
      )}
      {gap?.有缺口 && (
        <div className="gap-banner" role="alert">
          投影缺口：{(gap.原因 || []).join('；')} —— 名册汇总与事件真源分叉，请到对账页重放纠偏
        </div>
      )}
      <div className="row">
        <label>名称<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>负责人<input value={owner} onChange={(e) => setOwner(e.target.value)} /></label>
        <button type="button" onClick={create}>新建应用</button>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>编号</th><th>名称</th><th>负责人</th><th>状态</th>
              {envOrder.map((c) => <th key={c}>{c}版本</th>)}
              {envOrder.map((c) => <th key={c + '戳'}>{c}版本戳</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号}>
                <td>{r.编号}</td><td>{r.名称}</td><td>{r.负责人}</td><td>{r.状态}</td>
                {envOrder.map((c) => <td key={c}>{byApp[r.编号]?.列[c]?.版本 || '—'}</td>)}
                {envOrder.map((c) => <td key={c + '戳'}>{byApp[r.编号]?.列[c]?.版本戳 || '-'}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
