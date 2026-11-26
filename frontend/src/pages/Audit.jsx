import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Audit() {
  const [rows, setRows] = useState([])
  const [stamp, setStamp] = useState(null)
  const [gap, setGap] = useState(null)
  const [err, setErr] = useState('')
  const load = async () => {
    const d = await api('/审计')
    setRows(d.流水 || [])
    setStamp(d.投影 || null)
    setGap(d.投影缺口 || null)
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])
  return (
    <div className="panel">
      <h2>审计流水</h2>
      {err && <p className="err">{err}</p>}
      {stamp && (
        <p className="muted">
          审计刷新戳对齐投影 · 任务号 {stamp.投影任务号} · 刷新戳 {stamp.刷新戳 || '-'} ·
          事件位点 {stamp.事件位点} · 上次纠偏 {stamp.纠偏行数} 行
        </p>
      )}
      {gap?.有缺口 && (
        <div className="gap-banner" role="alert">
          投影缺口：{(gap.原因 || []).join('；')} —— 审计所据投影戳与事件真源不齐
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>类别</th><th>动作</th><th>关联</th><th>备注</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号}><td>{r.时间}</td><td>{r.类别}</td><td>{r.动作}</td><td>{r.关联编号 || '-'}</td><td>{r.备注}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button></div>
    </div>
  )
}
