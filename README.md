# 周期平铺织物组织设计器

设计师在网页上录入周期平铺的织物组织（交织格），系统按环向浮长规则校验原稿、
标出超限段，并求出**翻转未锁定格数量最少**的可行修补（同数时取按行展开
字典序最小的格值序列），展示翻转位置与修补预览；确认预览后才覆盖原稿。

- 后端：Python + Flask + SQLite（求解器基于 PySAT 的 MaxSAT/ SAT 编码）
- 前端：React（Vite 构建，由后端统一托管）
- 部署：Dockerfile + Docker Compose 一键启动，含依赖安装与数据库初始化

## 规则说明

- 格值：`0` 表示经线在上，`1` 表示纬线在上。
- 尺寸：1~16 行、1~8 列的非空矩形。
- 浮长：每行、每列的相同值连续段按**环向**计（左右、上下拼接边界算作相连），
  长度不得超过正整数 K；**全同的一行或一列视为无限浮长**（恒超限）。
- 修补：只能翻转未锁定格；目标为翻转数最少，并列时取按行展开字典序最小的格值序列。
- 无可行修补时保留原稿并报无解；尺寸、格值、K 不合法或编辑越界时拒绝操作。
- 预览后交织格、锁定格或 K 任一变动，旧预览即失效；只有确认当前预览才覆盖原稿，
  之后的编辑与预览基于最新原稿。

## 确认竞争与冲突处理

预览令牌在生成时绑定当时的原稿版本号，确认在**单个数据库事务内原子完成**
三项校验，任一不通过即回滚、拒绝确认且原稿不变：

1. 令牌存在且未被消费（重复确认、过期令牌 → `409`）；
2. 提交草稿与预览生成时的输入完全一致（草稿不匹配 → `409`，不消费令牌）；
3. 预览绑定的原稿版本仍是当前版本（期间已被他人确认推进 → `409`）。

三项全部通过才覆盖原稿、`version` 只递增一次并删除令牌。由此：

- 甲、乙基于同一原稿分别预览，甲确认后乙的旧令牌只能得到 `409`，无法覆盖甲的结果；
- 同一令牌并发/重复确认恰好生效一次，版本不会重复递增；
- 无可行修补的预览不发放令牌，始终不可确认；非法请求仍返回 `400`。

网页收到 `409` 后会清除旧预览、调用 `/api/state` 刷新原稿面板，
同时**保留本地未提交草稿**，并提示重新预览后再确认。

## 一键启动（Docker Compose）

```bash
docker compose up --build
```

启动后访问：

- 网页地址： <http://localhost:8000>
- 端口： `8000`（宿主机端口可在 `docker-compose.yml` 的 `ports` 中修改）

首次启动会自动初始化 SQLite 数据库（建表 + 写入一份默认原稿），
数据库文件保存在名为 `weave-data` 的卷中，容器重建后数据仍在。

停止：

```bash
docker compose down            # 保留数据卷
docker compose down -v         # 连同数据库一起删除
```

## 配置（环境变量）

| 变量      | 默认值            | 说明                       |
| --------- | ----------------- | -------------------------- |
| `PORT`    | `8000`            | 后端监听端口（容器内）     |
| `DB_PATH` | `/data/weave.db`  | SQLite 数据库文件路径      |

也可不用 Compose，直接构建镜像：

```bash
docker build -t weave-designer .
docker run -p 8000:8000 -v weave-data:/data weave-designer
```

## 本地开发（不用 Docker）

```bash
# 后端（Python 3.11+）
cd server
pip install -r requirements.txt
python app.py                 # 监听 http://localhost:8000

# 前端（Node 20+，另开终端；开发服务器代理 /api 到 8000 端口）
cd frontend
npm ci
npm run dev                   # http://localhost:5173

# 生产形态：构建前端后由 Flask 托管
cd frontend && npm run build
cp -r dist ../server/static
cd ../server && python app.py
```

后端调试模式：`FLASK_DEBUG=1 python app.py`（Flask 内置服务器，自动重载）。

## 运行测试

```bash
cd server
python test_solver.py      # 求解器正确性与性能
python test_confirm.py     # 确认竞争：版本绑定、原子事务、重复/并发/甲乙覆盖
```

测试内容：固定边界用例（全同、锁定冲突、环向跨界、K 极大等）、
60 组随机小网格与暴力枚举对照（翻转数最少 + 字典序最小）、
16×8 最大网格在各档 K 下的性能；
以及令牌重复/并发确认、甲乙旧令牌覆盖、草稿不匹配、非法请求、
无解不可确认等冲突场景。

## API 简介

| 方法 | 路径           | 说明                                                         |
| ---- | -------------- | ------------------------------------------------------------ |
| GET  | `/api/state`   | 返回当前原稿（尺寸、格值、锁定格、K、版本号）及其超限段      |
| POST | `/api/preview` | 提交草稿，返回超限段与最优修补（翻转位置、修补预览、令牌）；非法输入返回 400，无解时 `solvable=false`（不发令牌） |
| POST | `/api/confirm` | 携带预览令牌与当前草稿；原子校验令牌未消费、草稿与预览输入一致、原稿版本未变，通过才覆盖原稿；否则一律 `409`，非法请求 `400` |

### 调用示例

```bash
# 1. 查看当前原稿（注意 version 字段）
curl -s localhost:8000/api/state

# 2. 提交草稿预览，记录返回的 token
curl -s -X POST localhost:8000/api/preview \
  -H 'Content-Type: application/json' \
  -d '{"rows":4,"cols":4,
       "grid":[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],
       "locks":[],"k":2}'
# -> {"solvable":true,"token":"<令牌>","flipCount":8,
#     "repaired":[[...]],"flips":[[...]],"violations":[...],"input":{...}}

# 3. 携带同一令牌与当时草稿确认
curl -s -X POST localhost:8000/api/confirm \
  -H 'Content-Type: application/json' \
  -d '{"token":"<令牌>","rows":4,"cols":4,
       "grid":[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],
       "locks":[],"k":2}'
# -> {"state":{...,"version":2,"violations":[...]}}

# 4. 令牌已消费 / 原稿版本已变 / 草稿与预览不一致：
#    HTTP 409 {"error":"…旧预览已失效，请重新预览"}
#    此时应重新 GET /api/state 刷新原稿，并用当前草稿重新 POST /api/preview。
#    字段缺失或取值非法（如 k=0）：HTTP 400 {"error":"…"}
```

字段与响应结构均保持兼容：`/api/state`、`/api/preview`、`/api/confirm`
的请求字段和成功响应结构未变，仅冲突场景的拒绝更严格。

## 目录结构

```
├── Dockerfile              # 多阶段：前端构建 + 后端运行
├── docker-compose.yml      # 一键启动
├── server/                 # Python 后端
│   ├── app.py              # Flask 路由（state / preview / confirm）
│   ├── solver.py           # SAT/MaxSAT 最优修补求解
│   ├── weave.py            # 环向超限段检测
│   ├── validate.py         # 尺寸/格值/锁定/K 校验
│   ├── db.py               # SQLite 持久化与初始化
│   ├── test_solver.py      # 求解器测试（含暴力对照）
│   ├── test_confirm.py     # 预览确认竞争与冲突响应测试
│   └── requirements.txt
└── frontend/               # React 前端（Vite）
    └── src/
        ├── App.jsx         # 编辑器、预览、确认交互
        ├── weave.js        # 前端实时超限段检测
        └── api.js
```
