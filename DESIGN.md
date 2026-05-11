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
