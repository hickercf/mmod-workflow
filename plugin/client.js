// mmod-workflow DSH 插件 — Client 半（动态 Cordis Plugin，plain JavaScript）
//
// 在设置页（settings.section 槽位，id: mmod-workflow）注册「数学建模工作流」
// 8 步状态看板：S1–S8 状态色块、进度、8 秒自动刷新；通过 host.call('mmod-status')
// 从 Host 拉取引擎 JSON 状态。
return {
  inject: ['timer'],
  apply(ctx) {
    const slots = ctx.get('slots')
    if (slots === undefined) return

    const STATUS_TEXT = { pending: '待执行', running: '执行中', waiting_checkpoint: '待确认', rejected: '已打回', completed: '已完成' }
    const STATUS_COLOR = { pending: '#8b949e', running: '#d29922', waiting_checkpoint: '#58a6ff', rejected: '#f85149', completed: '#3fb950' }
    const thStyle = { textAlign: 'left', borderBottom: '1px solid #30363d', padding: '4px 8px' }
    const tdStyle = { borderBottom: '1px solid #21262d', padding: '4px 8px' }

    function StatusPanel() {
      const [workspace, setWorkspace] = React.useState('workspace/2025C-nipt')
      const [state, setState] = React.useState(null)
      const [error, setError] = React.useState(null)
      const [loading, setLoading] = React.useState(false)
      const load = React.useCallback((ws) => {
        setLoading(true)
        setError(null)
        host.call('mmod-status', { workspace: ws }).then((result) => {
          setState(result)
          if (!result || result.ok !== true) setError((result && result.error) || '读取失败')
        }).catch((err) => setError(String(err && err.message || err))).finally(() => setLoading(false))
      }, [])
      React.useEffect(() => { load(workspace) }, [workspace])
      React.useEffect(() => ctx.interval(() => load(workspace), 8000), [workspace])

      const rows = (state && state.steps) || []
      const completedCount = rows.filter((row) => row.status === 'completed').length
      return React.createElement('div', { style: { padding: '12px 16px', maxWidth: 720 } },
        React.createElement('h3', { style: { margin: '0 0 10px' } }, '数学建模工作流（comp_cumcm）'),
        React.createElement('div', { style: { display: 'flex', gap: 8, marginBottom: 8 } },
          React.createElement('input', { value: workspace, onChange: (e) => setWorkspace(e.target.value), placeholder: 'workspace/2025C-nipt', style: { flex: 1, padding: '4px 8px' } }),
          React.createElement('button', { onClick: () => load(workspace) }, '刷新'),
        ),
        React.createElement('div', { style: { fontSize: 12, color: '#8b949e', marginBottom: 8 } },
          '模板 ' + (state ? state.template : '-') + ' · 子问题 ' + (state ? state.subquestions : '-') + ' · 进度 ' + completedCount + '/' + rows.length + (loading ? ' · 刷新中…' : '') + '（每 8 秒自动刷新）'
        ),
        error ? React.createElement('div', { style: { color: '#f85149', fontSize: 12, marginBottom: 8 } }, '⚠ ' + error) : null,
        React.createElement('table', { style: { borderCollapse: 'collapse', width: '100%', fontSize: 13 } },
          React.createElement('thead', null, React.createElement('tr', null,
            ['步骤', '技能', '状态', '检查点'].map((h) => React.createElement('th', { key: h, style: thStyle }, h))
          )),
          React.createElement('tbody', null, rows.map((row) => {
            const text = STATUS_TEXT[row.status] || row.status
            const color = STATUS_COLOR[row.status] || null
            return React.createElement('tr', { key: row.id },
              React.createElement('td', { style: tdStyle }, row.id),
              React.createElement('td', { style: tdStyle }, row.skill),
              React.createElement('td', { style: color ? Object.assign({}, tdStyle, { color }) : tdStyle }, text),
              React.createElement('td', { style: tdStyle }, row.checkpoint || '-'))
          }))
        )
      )
    }

    slots.inject('settings.section', () => slots.register(
      { name: 'settings.section', id: 'mmod-workflow', order: 30, label: '数学建模工作流' },
      () => React.createElement(StatusPanel)
    ))
  },
}
