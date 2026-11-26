import React, { useEffect, useState } from 'react'
import { api } from '../api'

function ProjectionStamp({ p }) {
  if (!p) return null
  return (
    <p className="muted">
      分布真源：晋升放行事件重投影 · 投影任务号 {p.投影任务号} · 刷新戳 {p.刷新戳 || '-'} ·
      事件位点 {p.事件位点} · 上次纠偏 {p.纠偏行数} 行
    </p>
  )
}

function ProjectionGap({ gap }) {
  if (!gap?.有缺口) return null
  return (
    <div className="gap-banner" role="alert">
      投影缺口：{(gap.原因 || []).join('；')} · 差额 {gap.差额总数} 行 · 账本位点差 {gap.账本位点差}
      —— 名册汇总/投影戳与事件真源分叉，齐绿不可信，请到对账页按事件真源重放纠偏
    </div>
  )
}

export default function Overview() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  // 整体替换前不先清空旧数据，避免晋升撞刷新时半截分布闪旧格
  const load = () => {
    setLoading(true)
    return api('/总览')
      .then((d) => { setData(d); setErr('') })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])
  if (err) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中</div>
  const status = data.状态分布 || {}
  const dist = data.环境分布?.计数 || {}
  const order = data.环境分布?.四格顺序 || []
  return (
    <div className="panel">
      <h2>总览{loading ? '（刷新中）' : ''}</h2>
      <ProjectionStamp p={data.投影} />
      <ProjectionGap gap={data.投影缺口} />
      {!data.投影缺口?.有缺口 && (
        <p className="muted ok-line">名册汇总 · 投影任务戳 · 环境分布格 · 审计同指，对齐状态可重放验证</p>
      )}

      <h2>环境分布四格（事件重投影真源）</h2>
      <div className="grid">
        {order.map((k) => (
          <div className="stat" key={k}><div className="n">{dist[k] ?? 0}</div><div className="l">{k}</div></div>
        ))}
      </div>

      <h2>发版单状态桶（状态机维度）</h2>
      <div className="grid">
        {Object.entries(status).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
      </div>

      <h2>在途发版</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th><th>流水线</th></tr></thead>
          <tbody>
            {(data.在途 || []).map((r) => (
              <tr key={r.编号}><td>{r.发版单号}</td><td>{r.应用}</td><td>{r.目标版本}</td><td>{r.状态}</td><td>{r.当前环境 || '未落地'}</td><td>{r.流水线}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>各环境版本（名册投影，与四格同戳）</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>版本</th><th>版本戳</th></tr></thead>
          <tbody>
            {(data.环境版本 || []).map((v, i) => (
              <tr key={i}><td>{v.应用}</td><td>{v.环境}</td><td>{v.版本 || '—'}</td><td>{v.版本戳 || '-'}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={load} disabled={loading}>刷新</button></div>
    </div>
  )
}
