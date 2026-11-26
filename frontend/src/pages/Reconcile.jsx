import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Reconcile() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const load = () => api('/对账').then(setData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  const replay = async () => {
    setErr(''); setBusy(true)
    try {
      const out = await api('/投影/重放', { method: 'POST', body: JSON.stringify({}) })
      setErr(`已重放：任务号 ${out.投影.投影任务号}，纠偏 ${out.投影.纠偏行数} 行，重放前差额 ${out.重放前差额.差额总数} → 重放后 ${out.重放后差额.差额总数}`)
      await load()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  if (err && !data) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中</div>
  const s = data.发版统计 || {}
  const dist = data.环境分布?.计数 || {}
  const order = data.环境分布?.四格顺序 || []
  const diffs = data.对账差额 || {}
  return (
    <div className="panel">
      <h2>发布对账</h2>
      {err && <p className={err.startsWith('已重放') ? 'muted' : 'err'}>{err}</p>}
      {data.投影 && (
        <p className="muted">
          同一事件重投影 · 任务号 {data.投影.投影任务号} · 刷新戳 {data.投影.刷新戳 || '-'} ·
          事件位点 {data.投影.事件位点}
        </p>
      )}
      {data.投影缺口?.有缺口 && (
        <div className="gap-banner" role="alert">
          投影缺口未清，对账不得当已对齐：{(data.投影缺口.原因 || []).join('；')}
        </div>
      )}
      <div className="grid">
        <div className="stat">
          <div className="n">{data.对齐 ? '已对齐' : '未对齐'}</div>
          <div className="l">对齐状态</div>
        </div>
        {Object.entries(s).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
        <div className="stat"><div className="n">{data.晋升事件数}</div><div className="l">晋升事件数</div></div>
      </div>

      <h2>环境分布四格（与总览同源）</h2>
      <div className="grid">
        {order.map((k) => (
          <div className="stat" key={k}><div className="n">{dist[k] ?? 0}</div><div className="l">{k}</div></div>
        ))}
      </div>

      <h2>对账差额（缓存 vs 事件流真源）· 差额总数 {diffs.差额总数 ?? 0}</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>类型</th><th>对象</th><th>缓存</th><th>真源</th></tr></thead>
          <tbody>
            {(diffs.名册版本差额 || []).map((d, i) => (
              <tr key={'r' + i}><td>名册版本</td><td>{d.应用} · {d.环境}</td><td>{d.缓存版本 ?? '—'}</td><td>{d.真源版本 || '—'}</td></tr>
            ))}
            {(diffs.发版单环境差额 || []).map((d, i) => (
              <tr key={'e' + i}><td>发版单环境</td><td>发版单 {d.发版单编号}</td><td>{d.缓存环境编号 ?? '未落地'}</td><td>{d.真源环境编号 ?? '未落地'}</td></tr>
            ))}
            {(diffs.差额总数 || 0) === 0 && (
              <tr><td colSpan="4">零分叉：名册/发版单缓存与事件流真源一致</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <h2>名册与实例</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>名册版本</th><th>实例版本们</th><th>红灯数</th></tr></thead>
          <tbody>
            {(data.名册与实例 || []).map((r, i) => (
              <tr key={i}><td>{r.应用}</td><td>{r.环境}</td><td>{r.名册版本 || '—'}</td><td>{r.实例版本们 || '-'}</td><td>{r.红灯数}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        <button type="button" onClick={replay} disabled={busy}>{busy ? '重放中' : '按事件真源重放纠偏'}</button>
        <button type="button" className="secondary" onClick={load}>刷新</button>
      </div>
    </div>
  )
}
