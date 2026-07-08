# For Agents

├── worktrees.md (creating provisioned worktrees with `bin/worktree`)
├── style.md (code style guidelines for dimos)
├── code-quality-rules.md (code-quality rules agents scan/fix against)
├── python-syntax-guide.md (DimOS-specific Python patterns: @skill, In/Out, Protocol, async)
├── blueprint-call-path.md (一次 blueprint 调用路径：MCP → LCM RPC → worker skill，以 dax_agent/wave 为例)
├── dax-skill-sdk-yaml-path.md (dax_skill_sdk YAML 上半身：place/go_home、测试阶梯、与 HTTP wave 栈区分)
├── deploy-to-robot.md (开发机 dimos-deploy → 真机 /opt/dax-agent：git/rsync、uv sync、冒烟)
├── worker-models.md (Worker 辨析：线程池/进程池入门、n_workers vs num_workers、DimOS 并发栈)
├── dev-workflow-cn.md (需求确认 + 新建文件/新类中文 docstring)
├── testing.md (docs about writing tests)
├── docs (these are docs about writing docs)
│   ├── codeblocks.md
│   ├── doclinks.md
│   └── index.md
└── index.md
