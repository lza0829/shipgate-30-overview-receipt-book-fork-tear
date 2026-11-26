import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Health() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const load = () => api('/实例').then(setRows).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  const setH = async (id, health) => {
    setErr('')
    try {
      await api(`/实例/${id}/健康`, { method: 'POST', body: JSON.stringify({ 健康: health }) })
      load()
    } catch (e) { setErr(e.message) }
  }
  return (
    <div className="panel">
      <h2>健康探针</h2>
      {err && <p className="err">{err}</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>版本</th><th>健康</th><th>发版单</th><th>操作</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号}>
                <td>{r.应用}</td><td>{r.环境}</td><td>{r.版本}</td><td>{r.健康}</td><td>{r.发版单编号 || '-'}</td>
                <td>
                  <button type="button" onClick={() => setH(r.编号, '探针绿')}>探针绿</button>{' '}
                  <button type="button" className="danger" onClick={() => setH(r.编号, '探针红')}>探针红</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={load}>刷新</button></div>
    </div>
  )
}
