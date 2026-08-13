// mmod-workflow DSH 插件 — Host 半（动态 Cordis Plugin，plain JavaScript）
//
// 用法：在 DSH 会话中 cordis_define（kind: new, idPrefix: mmod），
//       本文件内容作为 code.host；client.js 内容作为 code.client；
//       然后 cordis_run 激活。依赖项目 scripts/workflow_engine.py 引擎
//       （工作区根 = 会话工作区，引擎路径相对该根：scripts/workflow_engine.py）。
return {
  inject: ['shell'],
  apply(ctx) {
    const sandboxPolicyService = ctx.get('sandboxPolicy')
    const ACTIONS = ['init', 'status', 'start', 'complete', 'gate', 'checkpoint', 'advance', 'resume', 'backfill', 'sync-state', 'report']
    const STEPS = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8']

    let cachedRoot = null
    let cachedPolicy = null

    function enc(value) {
      if (value == null || value === '') return ''
      const bytes = new TextEncoder().encode(String(value))
      let binary = ''
      for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
      return 'b64:' + btoa(binary)
    }

    function sessionContext(exec) {
      const agent = exec && exec.agent
      const session = agent && agent.session
      const cwd = session && session.header && session.header.cwd ? session.header.cwd : null
      let policy = null
      if (sandboxPolicyService) {
        try { policy = sandboxPolicyService.resolve(session ? { session } : {}) } catch (err) { policy = null }
      }
      if (cwd) cachedRoot = cwd
      if (policy && policy.workspaceRoot) cachedPolicy = policy
      return { cwd, policy }
    }

    function resolveWorkspace(value) {
      const v = String(value == null ? '' : value).trim()
      if (!v) throw new Error('workspace 必填，如 workspace/2025C-nipt')
      if (/^[A-Za-z]:[\\/]/.test(v) || v.startsWith('/') || v.startsWith('\\')) return v
      if (!cachedRoot) throw new Error('尚未初始化会话工作区；请先通过 mmod_workflow 工具执行一次任意动作')
      return cachedRoot + '\\' + v.replace(/[\\/]+$/, '')
    }

    function requireStep(step) {
      const value = String(step == null ? '' : step).toUpperCase().trim()
      if (STEPS.indexOf(value) < 0) throw new Error('step 必填且为 S1..S8')
      return value
    }

    async function runEngine(argv, signal) {
      const command = 'python scripts/workflow_engine.py ' + argv.join(' ')
      const request = { command, timeoutMs: 120000, stdoutMaxBytes: 400000 }
      if (cachedRoot) request.workdir = cachedRoot
      if (cachedPolicy) request.sandboxPolicy = cachedPolicy
      if (signal) request.signal = signal
      const spec = ctx.shell.resolve(request)
      const result = await ctx.shell.run(spec)
      const stdout = result.stdout && result.stdout.text ? result.stdout.text : ''
      const stderr = result.stderr && result.stderr.text ? result.stderr.text : ''
      return { exitCode: result.exitCode == null ? -1 : result.exitCode, stdout, stderr }
    }

    function buildArgv(args) {
      const action = String(args.action || '')
      if (ACTIONS.indexOf(action) < 0) throw new Error('未知 action: ' + action + '（可选 ' + ACTIONS.join('/') + '）')
      const ws = resolveWorkspace(args.workspace)
      const argv = [ws, action]
      if (action === 'init') {
        argv.push('--template', String(args.template || 'comp_cumcm'))
        if (args.subquestions != null) argv.push('--subquestions', String(args.subquestions))
        if (args.title) argv.push('--title', enc(args.title))
        if (args.force) argv.push('--force')
      } else if (action === 'start' || action === 'complete' || action === 'gate') {
        argv.push(requireStep(args.step))
        if (action === 'complete' && args.note) argv.push('--note', enc(args.note))
      } else if (action === 'checkpoint') {
        argv.push(requireStep(args.step))
        const ca = String(args.checkpoint_action || '')
        if (ca === 'resolve') {
          argv.push('resolve')
          if (args.response) argv.push('--response', enc(args.response))
        } else if (ca === 'reject') {
          argv.push('reject')
          if (!args.feedback) throw new Error('checkpoint reject 需要 feedback')
          argv.push('--feedback', enc(args.feedback))
        } else {
          throw new Error('checkpoint 需要 checkpoint_action: resolve|reject')
        }
      } else if (action === 'backfill') {
        if (args.steps) argv.push('--steps', String(args.steps))
        if (args.confirmed) argv.push('--confirmed', String(args.confirmed))
      } else if (action === 'sync-state') {
        if (args.check) argv.push('--check')
      } else if (action === 'status') {
        if (args.json) argv.push('--json')
      }
      return argv
    }

    const tool = harness.defineTool({
      name: 'mmod_workflow',
      description: '驱动数学建模统一工作流（comp_cumcm 8 步状态机：S1 审题→S2 建模赛马注册→S3 并行赛马求解→S4 深度证据→S5 图表→S6 论文→S7 评审三席盲评→S8 合规编译）。动作：init（建库）/ status / start / complete（跑质量门，失败则步骤保持 running）/ gate（只读）/ checkpoint resolve|reject（先 complete 进入 waiting_checkpoint）/ advance / resume（崩溃恢复）/ backfill（导入历史产物）/ sync-state（对齐 workflow-state.json）/ report。workspace 相对会话工作区（如 workspace/2025C-nipt）或绝对路径；step 为 S1..S8。',
      parameters: {
        type: 'object',
        properties: {
          action: { type: 'string', enum: ['init', 'status', 'start', 'complete', 'gate', 'checkpoint', 'advance', 'resume', 'backfill', 'sync-state', 'report'], description: '引擎动作' },
          workspace: { type: 'string', description: '工作区路径（相对会话工作区），如 workspace/2025C-nipt' },
          step: { type: 'string', description: 'S1..S8；start/complete/gate/checkpoint 必填' },
          checkpoint_action: { type: 'string', enum: ['resolve', 'reject'], description: 'checkpoint 动作' },
          response: { type: 'string', description: 'checkpoint resolve 的响应（JSON 或文本）' },
          feedback: { type: 'string', description: 'checkpoint reject 的反馈意见' },
          note: { type: 'string', description: 'complete 备注' },
          subquestions: { type: 'integer', description: 'init 的子问题数' },
          title: { type: 'string', description: 'init 的题名' },
          template: { type: 'string', description: 'init 模板名（默认 comp_cumcm）' },
          steps: { type: 'string', description: 'backfill 步骤列表，如 S1,S2,S3' },
          confirmed: { type: 'string', description: 'backfill 确认项，如 modeling,abstract,paper' },
          force: { type: 'boolean', description: 'init 强制重建' },
          json: { type: 'boolean', description: 'status 输出 JSON' },
          check: { type: 'boolean', description: 'sync-state 只读检查' },
        },
        required: ['action', 'workspace'],
      },
      output: {
        schema: {
          type: 'object',
          properties: {
            exitCode: { type: 'integer' },
            stdout: { type: 'string' },
            stderr: { type: 'string' },
          },
          additionalProperties: false,
        },
        render(args, value) {
          const lines = ['mmod_workflow ' + (args.action || '') + ' → exit ' + value.exitCode]
          if (value.stdout && String(value.stdout).trim()) lines.push(String(value.stdout).trim())
          if (value.stderr && String(value.stderr).trim()) lines.push('stderr: ' + String(value.stderr).trim())
          return [{ type: 'text', text: lines.join('\n') }]
        },
      },
      async execute(args, exec) {
        sessionContext(exec)
        const argv = buildArgv(args)
        return runEngine(argv, exec.signal)
      },
      timeoutMs: 120000,
    })

    const disposers = []
    disposers.push(harness.registerTool(ctx, tool))
    disposers.push(harness.handle('mmod-status', async (args) => {
      try {
        const ws = resolveWorkspace(args && args.workspace)
        const result = await runEngine([ws, 'status', '--json'], undefined)
        if (result.exitCode !== 0) {
          return { ok: false, workspace: ws, error: String(result.stderr || result.stdout || 'engine failed').trim().slice(0, 2000) }
        }
        const text = String(result.stdout || '').trim()
        const start = text.indexOf('{')
        if (start < 0) return { ok: false, workspace: ws, error: 'engine 未返回 JSON：' + text.slice(0, 300) }
        const payload = JSON.parse(text.slice(start))
        return { ok: true, workspace: ws, template: payload.template, subquestions: payload.subquestions, steps: payload.steps || [] }
      } catch (err) {
        return { ok: false, error: String(err && err.message || err) }
      }
    }))
    return () => { disposers.forEach((dispose) => { try { dispose() } catch (err) { console.error(err) } }) }
  },
}
