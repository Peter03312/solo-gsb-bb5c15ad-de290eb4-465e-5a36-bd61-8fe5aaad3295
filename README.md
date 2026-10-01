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
- 预览在生成时绑定当时的**原稿版本**；确认在单条数据库事务中原子校验
  「令牌未消费 + 提交草稿与预览输入逐字节一致 + 原稿版本未变」，
  三者同时成立才覆盖原稿（版本号恰好 +1）并消费令牌；任一不满足即整体回滚、
  原稿不变并返回 409（预览已失效）。因此并发或重复确认最多生效一次，
  甲确认后乙持有的旧令牌无法覆盖甲的结果。
- 网页收到 409 后会清除旧预览、重新拉取原稿、保留当前未提交草稿，
  并提示重新预览后再确认。

## 冲突处理（预览令牌与版本）

- `POST /api/preview`：服务端读取当前原稿版本 `v`，把规范化后的草稿输入
  （尺寸、格值、锁定、K）与求解结果、令牌、基础版本 `v` 一并落库；
  无解时返回 `solvable: false`，**不发放令牌**，不可确认。
- `POST /api/confirm`：请求字段不变（`token` 连同 `rows/cols/grid/locks/k`
  一起提交）。服务端在 `BEGIN IMMEDIATE` 写事务内完成校验与覆盖：

  | 情况                       | 结果        | 原稿/版本          |
  | -------------------------- | ----------- | ------------------ |
  | 令牌未消费、草稿一致、版本未变 | 200，覆盖原稿 | 原稿更新，版本 +1，令牌删除 |
  | 令牌不存在或已被确认（含并发重复提交） | 409 `consumed` | 不变 |
  | 草稿与预览输入不一致         | 409 `mismatch` | 不变 |
  | 预览绑定的原稿版本已被他人确认推进 | 409 `stale` | 不变 |
  | 无解预览、非法尺寸/格值/K     | 400（无解预览本身来自 preview 接口的 `solvable:false`） | 不变 |

  三种 409 响应体均为 `{"error": "…请重新预览"}`，原稿与版本号不发生任何变化；
  冲突后重新 `POST /api/preview` 取得新令牌即可正常确认。

### 调用示例

```bash
# 1. 查看原稿（含版本号）
curl -s http://localhost:8000/api/state
# {"rows":4,"cols":4,...,"version":1,"violations":[]}

# 2. 提交草稿预览，拿到令牌（无解时 solvable=false 且无 token）
curl -s -X POST http://localhost:8000/api/preview \
  -H 'Content-Type: application/json' \
  -d '{"rows":2,"cols":2,"grid":[[0,1],[0,1]],"locks":[],"k":2}'
# {"solvable":true,"token":"689b…","repaired":[[0,1],[1,0]], ...}

# 3. 携带令牌与同一份草稿确认
curl -s -X POST http://localhost:8000/api/confirm \
  -H 'Content-Type: application/json' \
  -d '{"token":"689b…","rows":2,"cols":2,"grid":[[0,1],[0,1]],"locks":[],"k":2}'
# {"state":{...,"version":2,"violations":[...]}}

# 4. 同一令牌再次确认（或他人已抢先确认、草稿已变动）-> 409，原稿不变
# {"error":"预览令牌不存在或已被确认，请重新预览"}
```

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
python test_solver.py
```

求解器测试内容：固定边界用例（全同、锁定冲突、环向跨界、K 极大等）、
60 组随机小网格与暴力枚举对照（翻转数最少 + 字典序最小）、
16×8 最大网格在各档 K 下的性能。

```bash
cd server
python test_confirm_race.py
```

确认竞争测试内容：成功确认版本恰好 +1、令牌消费后重复确认 409、
草稿不匹配 409、甲确认后乙的同原稿旧令牌 409、同一令牌 5 线程并发仅一次生效、
无解预览无令牌、非法请求 400、成功响应结构保持不变。

## API 简介

| 方法 | 路径           | 说明                                                         |
| ---- | -------------- | ------------------------------------------------------------ |
| GET  | `/api/state`   | 返回当前原稿（尺寸、格值、锁定格、K、版本号）及其超限段      |
| POST | `/api/preview` | 提交草稿，返回超限段与最优修补（翻转位置、修补预览、令牌）；非法输入返回 400，无解时 `solvable=false` |
| POST | `/api/confirm` | 携带预览令牌与当前草稿；原子校验令牌未消费、草稿与预览输入一致、原稿版本未变，成功才覆盖原稿（版本 +1）并消费令牌；重复/过期/草稿不匹配返回 409 且原稿不变 |

## 目录结构

```
├── Dockerfile              # 多阶段：前端构建 + 后端运行
├── docker-compose.yml      # 一键启动
├── server/                 # Python 后端
│   ├── app.py              # Flask 路由（state / preview / confirm）
│   ├── solver.py           # SAT/MaxSAT 最优修补求解
│   ├── weave.py            # 环向超限段检测
│   ├── validate.py         # 尺寸/格值/锁定/K 校验
│   ├── db.py               # SQLite 持久化与初始化（预览版本绑定 + 原子确认事务）
│   ├── test_solver.py      # 求解器测试（含暴力对照）
│   ├── test_confirm_race.py # 确认竞争端到端测试（含并发、冲突拒绝）
│   └── requirements.txt
└── frontend/               # React 前端（Vite）
    └── src/
        ├── App.jsx         # 编辑器、预览、确认交互
        ├── weave.js        # 前端实时超限段检测
        └── api.js
```
