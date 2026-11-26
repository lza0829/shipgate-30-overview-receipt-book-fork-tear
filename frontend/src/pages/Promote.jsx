import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Promote() {
  const [rows, setRows] = useState([])
  const [events, setEvents] = useState([])
  const [stamp, setStamp] = useState(null)
  const [gap, setGap] = useState(null)
  const [rid, setRid] = useState('')
  const [env, setEnv] = useState('预')
  const [err, setErr] = useState('')
  const [info, setInfo] = useState('')
  const load = async () => {
    const all = await api('/发版单')
    const active = all.filter((r) => ['已入闸', '晋升中'].includes(r.状态))
    setRows(active)
    const d = await api('/分布事件')
    setEvents(d.事件流 || [])
    setStamp(d.投影 || null)
    setGap(d.投影缺口 || null)
    if (!rid && active[0]) setRid(String(active[0].编号))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])
  const go = async () => {
    setErr(''); setInfo('')
    try {
      const out = await api(`/发版单/${rid}/晋升`, { method: 'POST', body: JSON.stringify({ 目标环境: env }) })
      const p = out.投影 || {}
      setInfo(`晋升已与投影同事务提交：任务号 ${p.投影任务号} · 刷新戳 ${p.刷新戳} · 事件位点 ${p.事件位点}`)
      await load()
    } catch (e) { setErr(e.message) }
  }
  return (
    <div className="panel">
      <h2>环境晋升</h2>
      {err && <p className="err">{err}</p>}
      {info && <p className="muted">{info}</p>}
      {stamp && (
        <p className="muted">分布真源事件流 · 投影任务号 {stamp.投影任务号} · 刷新戳 {stamp.刷新戳 || '-'} · 位点 {stamp.事件位点}</p>
      )}
      {gap?.有缺口 && (
        <div className="gap-banner" role="alert">
          投影缺口：{(gap.原因 || []).join('；')} —— 晋升前请先到对账页按事件真源重放纠偏
        </div>
      )}
      <div className="row">
        <label>发版单
          <select value={rid} onChange={(e) => setRid(e.target.value)}>
            {rows.map((r) => <option key={r.编号} value={r.编号}>{r.发版单号} · {r.应用} · {r.当前环境 || '未落地'}</option>)}
          </select>
        </label>
        <label>目标环境
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            <option value="测">测</option>
            <option value="预">预</option>
            <option value="产">产</option>
          </select>
        </label>
        <button type="button" onClick={go}>晋升</button>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号}><td>{r.发版单号}</td><td>{r.应用}</td><td>{r.目标版本}</td><td>{r.状态}</td><td>{r.当前环境 || '未落地'}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>分布事件流（真源，按重放顺序）</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>事件号</th><th>类型</th><th>应用</th><th>源环境</th><th>目标环境</th><th>版本</th><th>时间</th><th>备注</th></tr></thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.事件号}>
                <td>{e.事件号}</td><td>{e.类型}</td><td>{e.应用}</td>
                <td>{e.源环境 || '—'}</td><td>{e.目标环境 || '—'}</td>
                <td>{e.版本 || '—'}</td><td>{e.时间}</td><td>{e.备注}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
