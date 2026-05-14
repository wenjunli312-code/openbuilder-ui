# OpenBuilder Web UI - 极简 Demo 版本

## 目标

搭建一个最小的可运行版本，验证「网页发起 build → 下载产物」流程。

## 技术选型

| 层 | 方案 |
|----|------|
| 后端 | Flask（直接调用 openbuilder CLI） |
| 前端 | 单页 HTML + Vanilla JS（零框架） |
| 状态存储 | 本地 JSON 文件（无数据库） |
| 部署 | Docker Compose（Flask + 前端静态文件） |

## 目录结构

```
openbuilder-ui/
├── docker-compose.yml
├── backend/
│   ├── app.py              # Flask 主应用
│   ├── build_runner.py     # 调用 openbuilder CLI
│   ├── build_store.py      # Build 状态存储（JSON）
│   ├── requirements.txt
│   └── downloads/          # 产物下载目录
│       └── .gitkeep
├── frontend/
│   ├── index.html          # 单页应用
│   ├── style.css
│   └── app.js
└── nginx/
    └── nginx.conf          # 反向代理
```

## API 设计

### GET /api/builds
返回所有 build 列表

```json
{
  "builds": [
    {
      "id": "20260426_161730",
      "platform": "linux-arm64",
      "build_type": "debug",
      "status": "success",
      "created_at": "2026-04-26T16:17:30",
      "finished_at": "2026-04-26T16:18:45",
      "artifact_path": "outputs/20260426_161730.tar.gz",
      "log": "..."
    }
  ]
}
```

### POST /api/builds
发起新 build

Request:
```json
{
  "platform": "linux-arm64",
  "build_type": "debug"
}
```

Response:
```json
{
  "id": "20260426_162000",
  "status": "pending"
}
```

### GET /api/builds/<id>/download
下载 build 产物

## Build 状态机

```
pending → running → success
                    → failed
```

## 前端页面布局

```
┌────────────────────────────────────────────┐
│  OpenBuilder Dashboard                     │
├────────────────────────────────────────────┤
│  [+ New Build]                             │
│                                            │
│  Platform: [linux-arm64 ▼]  Type: [debug ▼]│
├────────────────────────────────────────────┤
│  Builds                                     │
│  ┌────────────────────────────────────────┐ │
│  │ 20260426_161730 | linux-arm64 | debug  │ │
│  │ Status: ✅ Success | [Download]        │ │
│  └────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────┐ │
│  │ 20260426_162000 | linux-arm64 | debug  │ │
│  │ Status: ⏳ Running...                   │ │
│  └────────────────────────────────────────┘ │
└────────────────────────────────────────────┘
```

## 实施步骤

### Step 1: 目录结构 + Docker Compose
搭建基础架子

### Step 2: Backend - build_store.py
JSON 文件读写

### Step 3: Backend - build_runner.py
subprocess 调用 openbuilder build

### Step 4: Backend - app.py
Flask API 端点

### Step 5: Frontend
HTML + CSS + JS 单页

### Step 6: 联调测试
手动验证完整流程

---

## 架构升级设计（讨论中，2026-05-12）

### 背景与目标

当前设计存在三个核心问题：
1. **下载包含所有平台产物** — `target/` 按 platform 子目录组织，但 publish 时打包了整个 `target/`
2. **多用户并发受限** — 所有 build 共享同一个 workspace，src/、build/、target/ 互相冲突
3. **缺乏增量编译机制** — 每次 build 都是 from-scratch，浪费编译时间

### 设计原则

1. **S3 作为唯一的真值来源** — 产物存储在 S3，以 manifest content hash 为 key
2. **Workspace pool 为临时 scratch 区** — 多 build 可并发，靠目录隔离
3. **资源隔离靠 Docker 容器** — 每个 build 在独立容器里跑，跑完即销毁

### 产物复用判断

**复用 key = `{platform} + {mode} + {manifest_content_hash}`**

`manifest_content_hash` 是**完整 manifest 内容**的 SHA256，而不是 commit hash。

理由：同一个 commit 下，编译选项、宏定义、CMAKE_CXX_FLAGS 等可以不同，产物也不同。只有完整的 manifest 内容才是构建配置的唯一真值来源。

示例：
```
key = linux-arm64+release+sha256:abc123...def456
   → s3://openbuilder-builds/artifacts/linux-arm64/release/abc123/target.tar.gz
```

### Build 流程

```
收到 build 请求
  → 计算 manifest_sha256
  → 查 S3 有没有这个 key 的产物
  → 有 → 从 S3 下载，解压到 workspace → 直接 publish（更新 S3 的 created_at）
  → 没有 → 从零编译 → publish 到 S3
```

### CMake 增量编译（单次 build 内）

`openbuilder build` 跑的是 `cmake --build`，CMake 本身会检测哪些 .cpp 变了，只重编变动的文件。这个在 workspace 内自然生效。

### S3 产物 vs Workspace 保留策略

| 组件 | 保留时间 | 作用 |
|------|---------|------|
| S3 产物 | 30 天 | 持久化存储，最终可下载，用户可回溯历史版本 |
| Workspace scratch | 7 天 | 增量编译加速，7 天内同 manifest 重复 build 直接复用 S3 产物 |

理由：S3 是最终备份，存储成本低；Workspace 只是 scratch 区，7 天够用了。

### Workspace Pool

**不是什么：** 不是每个 workspace 都是 Docker 容器。

**是什么：** 只是宿主机上的一组目录池（`/workspaces/ws-001/`、`/workspaces/ws-002/` …），用于多 build 并发时互不干扰地存放源码和 CMake 缓存。

```
宿主机
├── /workspaces/           ← workspace pool（普通目录，非容器）
│   ├── ws-001/           ← build-123 的 scratch 区
│   ├── ws-002/           ← build-456 的 scratch 区
│   └── ws-003/           ← [空闲]
├── /dockcross/...        ← 交叉编译镜像（这个才是 Docker）
```

**并发 5 个 build 的流程：**
```
请求 build-123 → 分配 ws-001 → clone 源码 → 从 S3 拉产物（如有）→ openbuilder build
请求 build-456 → 分配 ws-002 → ...
请求 build-789 → 分配 ws-003 → ...
请求 build-101 → 等 ws-001 归还 → ...
请求 build-111 → 等 ws-002 归还 → ...

ws-001 跑完 → publish S3 → workspace 清理（保留 7 天）→ 归还 pool
```

**资源隔离：**
- 跑 build 用 Docker 容器（`docker run --rm dockcross/...`），cgroup 限制 RAM/CPU
- Workspace 目录只是源码存放和 cmake 缓存位置，不占用额外资源
- 容器跑完即销毁，不持续占用系统资源

### 跨项目复用

如果 project A 和 project B 的 manifest 内容完全相同（same repos + same pinned commits + same options），它们会命中同一个 S3 key，产物直接复用。

如果 manifest 内容不同（如 pinned commit 不同、编译选项不同），则 key 不同，不复用——这是正确的行为，因为产物确实会不同。

### 打包粒度

当前问题：`openbuilder publish` 打包的是整个 `target/`，包含所有 platform 的产物。

改进：打包时只打包 `{platform}/{mode}/target/`，例如：
```
target/linux-arm64/release/   ← 只打包这个
target/linux-x86_64/debug/   ← 不打包
```

### 待确认事项

- [ ] S3 产物 30 天清理的 cron 策略（按 created_at 删除）
- [ ] Workspace 7 天后清理的策略（下次 build 时检查并清理过期的，或独立 cron）
- [ ] 用户在 UI 上是否需要看到"S3 命中缓存"的提示
- [ ] 初始 workspace pool 大小（建议 5-10 个，根据并发预期调整）
