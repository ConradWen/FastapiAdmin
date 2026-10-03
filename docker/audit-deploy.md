# FastapiAdmin 容器化 / 部署链路审计报告

- 审计任务：t6 — Docker 与部署运维审计（docker/ + deploy.sh + CI）
- 审计对象：`docker/`（compose、backend/Dockerfile、nginx、mysql、redis）、`deploy.sh`、`deploy-artifacts.sh`、`.github/workflows`、根 `.dockerignore`、`backend/env/*`
- 工作区：`/Users/tao/workspace/FastapiAdmin`，分支工作树（含未提交改动）
- 约束遵守：**只读审计**。未执行 `docker build` / `docker compose up`、未启动任何容器、未安装依赖、未提交 git；本报告是唯一新增文件。
- 证据标注规则：`文件:行号` 均为审计时刻工作区实际内容；实测命令输出见第 8 节。

---

## 1. 结论速览

### 1.1 上线前必须修（blocker / high）

| ID | 级别 | 一句话问题 | 关键证据 |
|----|------|-----------|---------|
| B1 | **blocker** | 生产环境从未注入 `SECRET_KEY`，JWT 签名 + 数据加密主密钥都是源码里的公开默认值 | `backend/app/config/setting.py:66`；`docker/docker-compose.yaml:99-119`；`backend/env/.env.prod`（无该键） |
| B2 | **blocker** | 按当前工作树构建后端镜像**必然失败**：pip 装依赖时 `requirements/base.txt` 还没被 COPY 进镜像 | `docker/backend/Dockerfile:14,17,20`；`backend/requirements.txt:12-16` |
| B3 | **blocker** | 真实 `OPENAI_API_KEY` 与生产库口令被 `COPY ./backend/ .` 烤进镜像层 | `docker/backend/Dockerfile:20`；`.dockerignore:18`（只排除 `.env`）；`backend/env/.env.prod` |
| H1 | high | MySQL(3306)/Redis(6379)/Backend(8001) 全部绑定 `0.0.0.0` 直接对公网暴露 | `docker/docker-compose.yaml:22-23,58-59,120-121`；`docker-compose config` 无任何 `host_ip` |
| H2 | high | `FORWARDED_ALLOW_IPS=*` + 8001 直连 → `X-Forwarded-For` 可伪造，绕过 IP 登录限流 | `docker/docker-compose.yaml:117-119`；`backend/app/config/setting.py:34,74` |
| H3 | high | 生产 TLS 私钥权限 `0666`（全局可写），pfx/jks 明文口令随目录一起上传 | `ls -l docker/nginx/ssl/server.key`；`docker/nginx/ssl/service.fastapiadmin.com/{nginx,iis,tomcat}/`；`docker/.env`（0644） |
| H4 | high | 证书纯手动更换、无自动续期、无到期告警；HTTP 块把 ACME http-01 校验路径也 301 到 HTTPS | `docker/nginx/nginx.conf:73-77,86-87`；证书 `notAfter=Mar 6 2027` |
| H5 | high | 没有任何 CI：`.github/workflows/` 是空目录 | `ls -laR .github/` 仅一个空 `workflows/` |
| H6 | high | 构建上下文约 68 MiB，内含 21 个 ssl 私钥文件与两套前端产物 | `.dockerignore` 未排除 `docker/`、`backend/dist`；实测 context≈68.4 MiB |
| H7 | high | 后端镜像以 root 运行，无 `no-new-privileges` / `cap_drop` / `read_only` | `docker/backend/Dockerfile`（26 行，无 `USER`）；`docker-compose.yaml:89-159`（无 `security_opt`） |
| H8 | high | `./deploy.sh` 会在全站停机式重建后**无论成败都打印"部署完成"并返回 0**，且无备份、无回滚 | `deploy.sh:78,106-113,125-137,141` |

### 1.2 可排期优化（medium / low）

| ID | 级别 | 一句话问题 | 关键证据 |
|----|------|-----------|---------|
| M1 | medium | nginx 只等 backend "已启动"而不等健康 → 冷启动窗口 502 | `docker-compose.yaml:178-180`（backend 自身有 healthcheck:138-147） |
| M2 | medium | `deploy.sh` 依赖探测允许独立版 `docker-compose`，其余流程却硬编码 `docker compose` | `deploy.sh:48` vs `deploy.sh:72,78,81,92,98,100,106,146` |
| M3 | medium | MySQL/Redis 口令以明文出现在容器 argv / healthcheck（`docker inspect` 可见） | `docker-compose.yaml:33,66,71`；`docker-compose config` 实测展开明文 |
| M4 | medium | 基础镜像全部浮动 tag，不可复现且 nginx 1.25 已非当前主线 | `docker-compose.yaml:13,53,164`；`docker/backend/Dockerfile:2` |
| M5 | medium | 数据面与前端面同网络、无 `stop_grace_period`、`container_name` 固定、mysql/redis 无 CPU 限制 | `docker-compose.yaml:12,52,90,163,217-219` |
| M6 | medium | 挂载宿主机 `/etc/localtime` 冗余且宿主缺文件时会导致容器启动失败 | `docker-compose.yaml:26`（对比 `TZ` 环境变量 17/57/100/168） |
| M7 | medium | 缺 HSTS / CSP / Permissions-Policy，无 OCSP stapling、无 `ssl_session_tickets off` | `docker/nginx/nginx.conf:58-63,85-92`（grep 全无命中） |
| M8 | medium | 全站无 Cache-Control/expires，带 hash 的 immutable 资源每次回源 | `docker/nginx/nginx.conf`（grep 无 `Cache-Control`/`expires`）；`docker/nginx/web/dist/js/index.*.js` |
| M9 | medium | `location /web`、`/app`、`/api/v1` 前缀匹配过宽；WS 头对所有 API 请求无条件设置 | `docker/nginx/nginx.conf:103,110,116,131-133` |
| M10 | medium | nginx 允许 50m 请求体而应用只收 10MB，等于把 40MB 无效流量灌进 Python | `docker/nginx/nginx.conf:30`；`backend/app/config/setting.py:223` |
| M11 | medium | nginx 健康检查只校验配置语法，证书过期/无法服务时仍是 healthy | `docker-compose.yaml:184` |
| M12 | medium | 部署过程无落盘审计日志、无版本记录；`cleanup()` 无条件清空构建缓存 | `deploy.sh:96-101,116-121,125-137` |
| M13 | medium | `.env` 以 `source` 方式 eval 执行；占位口令只在"首次生成文件"时被拦截 | `deploy.sh:26-38`；`docker/.env.example:4,9,12` |
| M14 | medium | 域名硬编码在 nginx.conf 与 setting.py，README 声称存在 `NGINX_SERVER_NAME` 变量但实际没有 | `docker/nginx/nginx.conf:75,83`；`backend/app/config/setting.py:186`；`docker/README.md:63` |
| M15 | medium | 真正带备份/回滚的部署脚本 `deploy-artifacts.sh` 未纳入版本管理，且硬编码生产 IP + root 登录 | `git ls-files deploy-artifacts.sh` 为空；`deploy-artifacts.sh:46-48` |
| L1 | low | `mysql/init` 是空目录，但 compose 注释与 README 声称"自动执行 init SQL" | `docker/docker-compose.yaml:27-28`；`docker/README.md:17` |
| L2 | low | `docker/README.md` 与实际实现严重漂移（含不存在的 CLI 参数、"自动拉取代码"、错误的访问地址） | `docker/README.md:87,93-103,132-138,219-221` vs `deploy.sh:5-6,143-161` |
| L3 | low | 镜像里带 22 MiB 旧前端产物，且 `app.frontend("/")` 注册 catch-all，未匹配路径返回 SPA 而非 JSON 404 | `backend/app/__init__.py:127-129`；`.dockerignore` 未排除 `backend/dist` |
| L4 | low | 镜像内保留大体积 source map（redoc standalone map 2.5 MiB 等） | `backend/static/swagger/redoc/bundles/redoc.standalone.js.map` |
| L5 | low | pip 源硬编码清华镜像，无法通过 build ARG 替换 | `docker/backend/Dockerfile:17` |
| L6 | low | `ENV TZ Asia/Shanghai` 使用已废弃的空格语法；Dockerfile 无 `HEALTHCHECK` | `docker/backend/Dockerfile:8` |
| L7 | low | `mkdir -p` 建数据目录但不修属主（MySQL 需 999:999） | `deploy.sh:41`；`docker/README.md:206` |

---

## 2. 上线前必须修（详细）

### B1 [blocker] 生产 `SECRET_KEY` 使用源码内公开默认值 → JWT 可伪造 + 落库密文可解密

**证据**

- `backend/app/config/setting.py:66`：
  ```python
  SECRET_KEY: str = "fastapiadmin-dev-secret-key-do-not-use-in-production"  # JWT密钥（必须通过环境变量 SECRET_KEY 设置，无默认值）
  ```
  注释说"无默认值"，实际有默认值。
- 全仓库检索 `SECRET_KEY` 赋值来源（`.venv/`、`node_modules/` 除外）**只命中**：测试用的 `backend/tests/conftest.py:32` 与源码默认值本身。
- `docker/docker-compose.yaml:99-119` 的 backend `environment` 列表里没有 `SECRET_KEY`，也没有 `env_file:`。
- `docker/.env.example`（26 行）无 `SECRET_KEY`；`backend/env/.env.prod` 键清单（实测 awk 抽取）无 `SECRET_KEY`；`backend/env/.env.example:2` 只在**注释**里提到要改 `SECRET_KEY`。
- 该密钥还被复用为数据加密主密钥：`backend/app/utils/crypto_util.py:47-52` 在 `DATA_ENCRYPTION_KEY` 未配置时用 `SECRET_KEY` 做 HKDF 派生主密钥，`crypto_util.py:52` 还兼容 `SHA256(SECRET_KEY)` 的历史密文。`DATA_ENCRYPTION_KEY` 同样未在 compose 与 `.env.prod` 中出现（`setting.py:79` 默认 `None`）。

**影响**：任何读到过源码的人都能签发任意用户（含 admin）的有效 access/refresh token（`backend/app/core/security.py:114,139`）；同时可解密数据库里用 Fernet 加密的存储源口令等敏感数据。

**改法**

1. `docker/docker-compose.yaml` backend 服务增加密钥注入（三选一，推荐 1）：
   ```yaml
   environment:
     SECRET_KEY: "${SECRET_KEY:?错误: 请设置 SECRET_KEY 环境变量}"
     DATA_ENCRYPTION_KEY: "${DATA_ENCRYPTION_KEY:?错误: 请设置 DATA_ENCRYPTION_KEY 环境变量}"
   ```
   或在 `docker/.env` 中定义后由 compose 自动读取，并把两行加入 `docker/.env.example`。
2. `backend/env/.env.prod` 与 `backend/env/.env.example` 补齐 `SECRET_KEY`、`DATA_ENCRYPTION_KEY` 键位（值留空）。
3. 生成：`openssl rand -hex 32`。
4. 加一道启动自检（后端或部署脚本均可）：若 `SECRET_KEY` 等于默认值则拒绝启动。
5. 轮换顺序：先配 `DATA_ENCRYPTION_KEY`=旧 `SECRET_KEY` 的派生等价物或用 `DATA_ENCRYPTION_OLD_KEYS` 过渡，再换 `SECRET_KEY`（`crypto_util.py:47-62` 有旧密钥解密链），避免已落库密文不可解。

---

### B2 [blocker] 当前工作树后端镜像**必然构建失败**（依赖层顺序错误）

**证据**

`docker/backend/Dockerfile`：

```
14: COPY ./backend/requirements.txt .          # → /home/requirements.txt
17: RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
20: COPY ./backend/ .                          # → /home/requirements/ 在这一层才出现
```

而工作树 `backend/requirements.txt:10-14` 已经是拆分后的组合式清单：

```
-r requirements/base.txt
-r requirements/db/mysql.txt
-r requirements/db/postgres.txt
-r requirements/db/sqlite.txt
-r requirements/storage.txt
```

（**证据时效**：该文件在审计期间被其他并行审计成员修改过，行号由 12-16 变为 10-14；上述 `-r` 引用内容本身未变，已复核。）

`backend/requirements/base.txt` 等 5 个文件位于 `backend/requirements/`，而 `git ls-files backend/requirements/` **输出为空**（该目录尚未提交，`git status` 显示 `?? backend/requirements/`）。

**判定**：第 17 行执行时 `/home` 下只有 `requirements.txt`。pip 对 `-r` 相对路径的解析基准无论是"当前工作目录 `/home`"还是"清单文件所在目录 `/home`"，目标都落在 `/home/requirements/base.txt` —— 该路径在本层尚不存在（第 20 行才 COPY）。因此 `docker compose build` 与 `deploy.sh` 的 `build_image()` 都会以 `Could not open requirements file: ... requirements/base.txt` 失败。

**改法**（任选其一）

- 推荐：把依赖清单目录先 COPY 再安装，并按数据库类型只装所需驱动：
  ```dockerfile
  COPY ./backend/requirements/ /home/requirements/
  RUN pip install --no-cache-dir \
        -r /home/requirements/base.txt \
        -r /home/requirements/db/mysql.txt \
        -r /home/requirements/storage.txt
  ```
- 或者把 `backend/requirements/` 提交进仓库，并同步更新 `requirements.txt` 的引用路径。

> 对照：`deploy-artifacts.sh` 动态生成的 Dockerfile 已经写对了顺序（先 `COPY requirements/ /home/requirements/` 再 `pip install -r /home/requirements/base.txt`），说明这是**仓库内 Dockerfile 未跟上依赖拆分**导致的不一致。

---

### B3 [blocker] 真实 `OPENAI_API_KEY` 与生产库口令被烤进后端镜像

**证据**

- `docker/backend/Dockerfile:20`：`COPY ./backend/ .` —— 把整个 `backend/` 复制进镜像 `/home`，包含 `backend/env/`。
- 根 `.dockerignore:18` 只有一行 `.env`；dockerignore 的 `.env` 只匹配名为 `.env` 的文件/目录，**不匹配** `backend/env/.env.prod`、`backend/env/.env.dev`。
- 实测 `backend/env/.env.prod` 键值特征（脱敏，仅长度与前 4 字符）：`OPENAI_API_KEY` 长度 35、以 `sk-d` 开头；`DATABASE_PASSWORD` 长度 13、`REDIS_PASSWORD` 长度 13；`DATABASE_HOST` 为 `172.x` 内网地址、`DATABASE_USER=root`。这些都是真实可用凭据，非占位串。
- 反证团队已知该风险：`deploy-artifacts.sh` 在构建时用 Python 脚本显式剔除 `OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL`（脚本内 `drop_prefixes`），但仓库内的 `docker/backend/Dockerfile` 没有任何等效处理。
- 附带：`backend/env/.env.prod` 还是运行时配置的实际来源（`setting.py:16-21` 以 `ENV_DIR/.env.{ENVIRONMENT}` 为 `env_file`，`path_conf.py:4,16` → `/home/env/.env.prod`），compose 只覆盖了 DB/Redis 相关键，`OPENAI_API_KEY` 等继续取自镜像内文件。

**影响**：任何拿到镜像的人（`docker save`、镜像仓库、构建缓存、离线交付包）都能取走生产大模型 API Key；同理 `DATABASE_HOST/USER` 泄露内网拓扑。

**改法**

1. `.dockerignore` 增加排除（放在第 18 行附近）：
   ```
   backend/env/.env
   backend/env/.env.*
   !backend/env/.env.example
   ```
2. Dockerfile 改为**白名单式 COPY**（更彻底）：
   ```dockerfile
   COPY ./backend/app ./app
   COPY ./backend/main.py ./main.py
   COPY ./backend/alembic.ini ./alembic.ini
   COPY ./backend/static ./static
   COPY ./backend/sql ./sql
   COPY ./backend/templates ./templates
   COPY ./backend/data ./data
   COPY ./backend/banner.txt ./banner.txt
   ```
   运行时配置全部由 compose `environment` / `env_file` 注入。
3. 既然密钥已进过镜像层：**视为已泄露，上线前轮换** `OPENAI_API_KEY`、MySQL/Redis 口令，并清理本机悬空构建缓存。

---

### H1 [high] MySQL / Redis / Backend 端口直接对公网暴露

**证据**

- `docker/docker-compose.yaml:22-23`：`- "${MYSQL_PORT:-3306}:3306"`
- `docker/docker-compose.yaml:58-59`：`- "${REDIS_PORT:-6379}:6379"`
- `docker/docker-compose.yaml:120-121`：`- "${BACKEND_PORT:-8001}:8001"`
- 三处都没有 `127.0.0.1:` 前缀；实测 `cd docker && docker-compose config` 输出的 `ports` 条目中 `host_ip` 字段一个都没有（`grep -c host_ip` = 0），即全部绑定 `0.0.0.0`。
- `docker/redis/conf/redis.conf`（17 行）没有 `bind`、没有 `protected-mode yes`，只有 `requirepass` 由 compose `command` 注入（`docker-compose.yaml:64-66`）。
- `docker/README.md:195` 自己写着"生产环境建议注释 MySQL/Redis 的 ports 映射"，`docker/README.md:214` 写着"通过防火墙只开放 80/443" —— 但 compose 默认值并未落实。

**影响**：只要云安全组/主机防火墙放行，3306 与 6379 直接可被爆破与未授权探测；8001 直连会**绕过 nginx 的限流、安全响应头、HTTPS 与上传限制**，并暴露 `/api/v1/docs`。

**改法**

```yaml
  mysql:
    ports:
      - "127.0.0.1:${MYSQL_PORT:-3306}:3306"   # 仅本机调试；生产建议整段删除
  redis:
    ports:
      - "127.0.0.1:${REDIS_PORT:-6379}:6379"
  backend:
    ports:
      - "127.0.0.1:${BACKEND_PORT:-8001}:8001"
```
更彻底：删掉 mysql/redis 的 `ports:`（容器间用 `app_network` 互通即可），backend 同样删除，只保留 nginx 的 80/443；并在云安全组层面显式拒绝 3306/6379/8001 入方向。
另外在 `redis.conf` 补 `bind 0.0.0.0` + `protected-mode yes` 只是兜底，真正的收敛靠端口绑定。

---

### H2 [high] `FORWARDED_ALLOW_IPS=*` 配合 8001 直连 → 可伪造客户端 IP 绕过限流

**证据**

- `docker/docker-compose.yaml:117-119`：
  ```yaml
  # 信任反向代理（nginx）传来的 X-Forwarded-Proto/For
  FORWARDED_ALLOW_IPS: "*"
  ```
- 结合 H1：backend:8001 绑定 `0.0.0.0`，攻击者可直连 8001 并自带 `X-Forwarded-For: 1.2.3.4`。
- 依赖客户端 IP 的安全控制：`backend/app/config/setting.py:73-74`（`LOGIN_RATE_LIMIT_MAX_ATTEMPTS=10` 按 IP 限流）、`setting.py:34`（`TRUSTED_PROXY_HOPS=1`）、以及操作日志 / 在线用户记录。`backend/env/.env.example` 里的 `TRUSTED_PROXY_HOPS` 注释明确写了"后端直接暴露公网时填 0，防止 X-Forwarded-For 伪造"——但 compose 没有设这个值，且 8001 恰恰是暴露的。

**改法**

1. 先按 H1 收敛端口（首要）。
2. `FORWARDED_ALLOW_IPS` 改为 nginx 所在的具体网段而非 `*`，例如固定网络后写 `172.18.0.0/16`；不要用 `*`。
3. 若确实需要保留宿主机直连调试，同时在 compose 给 backend 加 `TRUSTED_PROXY_HOPS: "0"`。

---

### H3 [high] TLS 私钥权限过大 + pfx/jks 明文口令随目录上传

**证据**（实测 `ls -l`）

```
-rw-r--r--@ docker/.env
-rw-rw-rw-@ docker/nginx/ssl/server.key            # 0666
-rw-rw-rw-@ docker/nginx/ssl/server.pem            # 0666
-rw-rw-rw-@ docker/nginx/ssl/service.fastapiadmin.com/nginx/service.fastapiadmin.com.key
-rw-rw-rw-@ docker/nginx/ssl/service.fastapiadmin.com/nginx/service.fastapiadmin.com.crt
```

- `docker/nginx/ssl/service.fastapiadmin.com/iis/password.txt`、`.../tomcat/password.txt` 各 6 字节明文口令（用于 pfx/jks 导出）。
- `docker/nginx/ssl/service.fastapiadmin.com.zip` 是证书打包文件。
- `docker/.env` 权限 0644（全局可读），而 `docker/README.md:45` 明确要求 `chmod 600 docker/.env`；`deploy.sh:29-33` 用 `cp .env.example .env` 生成文件时也不会改权限。
- 好消息：证书/私钥/`.env` 都**没有**被 git 跟踪（`.gitignore` 覆盖 `docker/nginx/ssl/*`、`docker/.env`；`git ls-files docker/` 已确认只有 `.gitkeep` 与配置模板）。
- 但 `deploy.sh:5-6` 的部署模型是"把项目目录整体 scp/FTP 上传服务器"，`.env`、`server.key`、`*.zip`、`password.txt` 会**原样落到服务器磁盘**，权限一并带过去；同时它们也落在 Docker 构建上下文里（见 H6）。

**改法**

1. 立即收紧：`chmod 700 docker/nginx/ssl && chmod 600 docker/nginx/ssl/*.key docker/.env`；`deploy.sh` 在 `load_env` 后加 `chmod 600 "${ENV_FILE}"` 与 `find docker/nginx/ssl -name '*.key' -exec chmod 600 {} +`。
2. 把 `service.fastapiadmin.com/`（含 iis/tomcat 的 pfx/jks/password.txt）与 `*.zip` 移出仓库工作目录，只在服务器上保留 nginx 需要的 `fullchain.pem` + `privkey.pem` 两份。
3. 密钥交给 Docker secret / 宿主只读挂载（`docker/nginx/ssl` 已是 `:ro`，见 `docker-compose.yaml:175`，这点是对的），并在 `.gitignore` 之外加一道 pre-commit 检查防止误传。
4. 若这些证书曾进入过镜像或构建缓存，按"已泄露"处理。

---

### H4 [high] 证书手动更换、无续期、无到期监控；HTTP 块阻断 ACME http-01

**证据**

- `docker/nginx/nginx.conf:86-87` 固定读取 `/etc/nginx/ssl/server.pem` 与 `/etc/nginx/ssl/server.key`；`docker-compose.yaml:175` 把 `./nginx/ssl` 只读挂进容器。
- 证书实测（`openssl x509 -noout -subject -issuer -dates`）：
  - Subject：`CN=service.fastapiadmin.com`
  - Issuer：`C=PL/O=Asseco Data Systems S.A./CN=Certum DV TLS G2 R39 CA`
  - `notBefore=Aug 19 14:10:22 2026 GMT`，`notAfter=Mar 6 14:10:21 2027 GMT`
  - SAN：`DNS:service.fastapiadmin.com`（单域名，无通配符）
  - `server.pem` 与 CA 交付的 `.crt` 内容一致（md5 相同），且与 `server.key` 公钥匹配（pubkey md5 相同）→ 配置与证书是配套的，这点没问题。
- `docker/nginx/nginx.conf:73-77` 的 80 端口 server 把**所有**请求 `return 301 https://...`，其中没有 `location /.well-known/acme-challenge/` 例外 → Let's Encrypt http-01 校验会跟随 301 到 HTTPS（对同名域名通常仍可完成校验，但一旦 `server_name` 不匹配或走 IP 校验就会失败）。仓库内也没有任何 acme.sh / certbot / systemd timer / cron 配置。

**影响**：证书 2027-03-06 到期，而链路上没有任何机制会提醒；历史上"到期当天才发现"的概率很高。

**改法**

1. `docker/nginx/nginx.conf:73-77` 的 HTTP server 增加：
   ```nginx
   location /.well-known/acme-challenge/ { root /usr/share/nginx/html; allow all; }
   ```
2. 用 acme.sh（DNS-01 或 http-01）自动签发与续期，续期钩子：
   `acme.sh --install-cert -d service.fastapiadmin.com --key-file docker/nginx/ssl/server.key --fullchain-file docker/nginx/ssl/server.pem --reloadcmd "docker compose -f docker/docker-compose.yaml exec nginx nginx -s reload"`
3. 加到期检查（cron 每天）：
   ```bash
   openssl x509 -in docker/nginx/ssl/server.pem -noout -checkend 1209600 || echo "证书 14 天内到期" | <告警通道>
   ```
4. 同步把 `nginx -t` 之类的健康检查升级为带 HTTPS 探测（见 M11）。

---

### H5 [high] 没有任何 CI

**证据**：`ls -laR .github/` 输出 `workflows/` 为空目录（`total 0`，无任何文件）；仓库内也不存在其他 CI 配置（`.gitlab-ci.yml`、`Jenkinsfile`、`.woodpecker.yml` 等均无；`find` 命中的 yaml 只有 compose 与前端配置）。

**影响**：没有自动门禁意味着本报告 B2 这类"依赖层顺序写错、镜像根本构建不出来"的问题**只能在生产部署时暴露**；也没有镜像漏洞扫描、没有配置校验、没有后端测试门禁。

**改法**：新增 `.github/workflows/ci.yml`，至少包含

1. `docker compose -f docker/docker-compose.yaml config -q`（配置/变量插值校验，需提供 dummy env）
2. `docker build -f docker/backend/Dockerfile .`（不 push，仅验证依赖层可解）
3. `ruff check backend` + `pytest backend/tests`
4. 镜像分层扫描：`trivy image --severity HIGH,CRITICAL`
5. 触发条件 `on: [push, pull_request]`，`paths` 覆盖 `docker/**`、`backend/**`、`.dockerignore`

---

### H6 [high] 构建上下文臃肿且包含私钥（约 68 MiB，21 个密钥文件）

**证据**（实测）

- 根 `.dockerignore` 未排除 `docker/`、`backend/dist`、`backend/tests`、`backend/data`、`.agent-teams`、`*.zip`。
- 按 `.dockerignore` 规则静态估算的上下文体积：**≈68.4 MiB**，主要构成（实测逐个文件统计）：
  - `backend/data/ip2region/ip2region_v4.xdb` 10.61 MiB（运行时需要，保留）
  - `docker/nginx/web/dist/**` ≈2.55+1.91+1.53+1.38+1.33 MiB… 合计 ≈22 MiB（**死重**）
  - `backend/dist/**` ≈22 MiB（**死重**，见 L3）
  - `backend/static/swagger/**` 数 MiB（含 `.map`）
  - `docker/nginx/ssl/**` **21 个文件**（含 `server.key`、`service.fastapiadmin.com/**/*.key`、`.zip`、`password.txt`）
- 对比：被正确排除的有 `.git`（151 MiB）、`backend/.venv`（231 MiB）、`frontend`（1.5 GiB）、`backend/logs`（6.5 MiB）——这部分是好的。

**影响**：每次构建把 68 MiB 上下文送给构建守护进程（远程 daemon / colima / BuildKit 场景下走网络），其中含生产私钥；`COPY ./backend/ .` 的改变会让 22 MiB 的 `backend/dist` 一起进镜像层。

**改法**：在根 `.dockerignore` 追加

```
# 容器资产不进后端构建上下文（含 TLS 私钥）
docker/
# 后端镜像不需要的产物
backend/dist
backend/tests
backend/data/logs
.agent-teams
docker/nginx
*.zip
```

注意 `backend/data/ip2region` 必须保留（`backend/app/config/path_conf.py:31-32` 依赖该库做 IP 归属地查询），所以只排除 `backend/data/logs`，不要整目录排除 `backend/data`。
若同时想减小上下文，可把 `deploy.sh` 改为在 `docker/` 目录内构建（`build.context: ../` 目前是根目录，这也是私钥进上下文的原因）。

---

### H7 [high] 镜像以 root 运行，缺少容器安全基线

**证据**：`docker/backend/Dockerfile` 全文 26 行，**没有 `USER` 指令**；没有 `PYTHONUNBUFFERED` / `PYTHONDONTWRITEBYTECODE`；没有进程管理器（tini 等）。`docker/docker-compose.yaml` 四个服务（9-219 行）都没有 `security_opt`、`cap_drop`、`read_only`、`user:`。

**影响**：容器逃逸/依赖链漏洞时以 root 权限作业；`/home` 可写导致代码被覆盖；缺 `no-new-privileges` 让 setuid 提权路径保持开放。

**改法**

```dockerfile
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LANG=C.UTF-8
RUN useradd -m -u 10001 app && mkdir -p /home/logs /home/static/upload && chown -R app:app /home
USER app
```

compose 侧：

```yaml
    init: true
    security_opt: ["no-new-privileges:true"]
    cap_drop: ["ALL"]
    read_only: true
    tmpfs: ["/tmp"]
```

配套注意：`docker-compose.yaml:130` 的 `./backend/static/upload:/home/static/upload` 挂载需要把宿主目录属主改成 uid 10001，否则上传会失败（这是改非 root 后最容易踩的坑）。

---

### H8 [high] `./deploy.sh` 失败也会报"部署完成"并返回 0；且无备份、无回滚、整站重建

**证据**（均在 `deploy.sh`）

- **无条件全量重建**：第 78 行 `docker compose up -d --force-recreate`（未指定服务名）→ MySQL、Redis、nginx 一并被销毁重建，每次部署都是一次全站停机。
- **健康门禁形同虚设**：
  - 第 80-85 行等待 MySQL healthy 循环 30 次，超时后**不报错**，直接继续。
  - 第 106-113 行 `verify()` 无论成败，最后一条语句都是 `log`（`echo -e`），必然返回 0；第 113 行 `$ok && log ... || log ...` 两个分支都是成功退出。
  - 第 125-137 行 `full_deploy` 不管 `verify` 结果继续执行 `show_logs`、`cleanup`，最后打印 `========== 🎉 部署完成 ==========`。
  - 结论：4 个容器全部 down 时，`./deploy.sh; echo $?` 仍是 `0`。
- **无备份无回滚**：整脚本没有 `mysqldump`、没有静态目录备份、没有镜像版本留存；`docker-compose.yaml:96` 的 `image: "backend:${BACKEND_IMAGE_TAG:-3.0.0}"` 是固定 tag，重新构建即覆盖上一版 → 没有可回退的镜像。
- **Ctrl-C 变成全站下线**：第 141 行 `trap 'stop_service; exit 130' INT TERM`，而 `stop_service`（90-94）执行 `docker compose down`。
- **清理激进**：第 118-119 行 `docker image prune -f` + `docker builder prune -f` 会清空构建缓存，下一次构建从零开始（且 `builder prune -f` 在 BuildKit 下会丢弃所有缓存）。

**改法**（可直接复用 `deploy-artifacts.sh` 的成熟做法）

1. **部署前备份**（必做）：
   ```bash
   mkdir -p backups
   docker compose exec -T mysql sh -c 'exec mysqldump --single-transaction --routines --triggers -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' | gzip > "backups/db-$(date +%F-%H%M%S).sql.gz"
   tar -czf "backups/nginx-$(date +%F-%H%M%S).tgz" docker/nginx/web/dist docker/nginx/app docker/nginx/docs
   cp docker/.env "backups/env-$(date +%F-%H%M%S)"
   ```
2. **镜像版本化**：构建后 `docker tag backend:3.0.0 "backend:$(date +%Y%m%d-%H%M%S)"`，并把当前在跑的 tag 固定为 `backend:prev`（`deploy-artifacts.sh` 的 `_rollback_image` 已实现）。
3. **只重建变化的服务**：`docker compose up -d --no-deps --force-recreate backend`，不要动 mysql/redis/nginx。
4. **健康门禁**：轮询 `docker inspect --format '{{.State.Health.Status}}' backend` 直到 `healthy`，超时即 `exit 1` 并自动回滚到 `backend:prev`。
5. **`verify()` 必须能失败**：改为累积状态并在末尾 `[ "$ok" = true ] || exit 1`，且增加真实 HTTP 探测（`curl -fsS https://域名/api/v1/monitor/health/check`）。
6. **改掉 trap**：`trap 'log "中断，未做任何回滚" WARN; exit 130' INT TERM`，不要在中断时 `down`。
7. **清理改为显式命令**：`cleanup` 只在 `./deploy.sh clean` 时调用，且去掉 `docker builder prune`。

---

## 3. 分项审计明细

### 3.1 docker-compose（`docker/docker-compose.yaml`，219 行）

| 审计项 | 现状 | 结论 |
|--------|------|------|
| 语法与变量校验 | `docker-compose config` 退出码 0（实测，见第 8 节） | ✅ 通过；`${VAR:?}` 必填校验生效（18,21,66 行，缺变量会直接报错并给出中文提示） |
| 端口暴露 | mysql 3306 / redis 6379 / backend 8001 全部 `0.0.0.0`（22-23,58-59,120-121） | ❌ **H1** |
| 健康检查 | 四个服务都有 healthcheck（31-37,69-75,138-147,183-187） | ⚠️ 覆盖到位，但 mysql/redis 口令进 argv（**M3**），nginx 只 `nginx -t`（**M11**） |
| 依赖顺序 | nginx → backend 用 `service_started`（178-180）；backend → mysql/redis 用 `service_healthy`（131-135） | ⚠️ backend 的两条依赖正确，nginx 这条应改 `service_healthy`（**M1**） |
| restart 策略 | 四服务均 `unless-stopped`（14,54,97,165） | ✅ |
| 资源限制 | backend 1 CPU/1 GB，nginx 0.5 CPU/256 MB，mysql 1 GB，redis 512 MB（43-48,81-86,153-159,193-199） | ⚠️ mysql/redis 无 CPU 上限；compose v2 会尊重 `deploy.resources.limits`，但 `reservations` 在非 swarm 下被忽略 |
| 日志滚动 | 四服务均 `json-file` + `max-size: 10m` + `max-file: 3`（38-42,76-80,148-152,188-192） | ✅ 与 `docker/README.md:164` 一致 |
| 数据卷与权限 | `mysql_data`/`redis_data` 用 `driver_opts` bind 到 `./mysql/data`、`./redis/data`（202-214）；实测 config 解析为绝对路径 `/Users/tao/.../docker/mysql/data` | ✅ 结构正确；⚠️ 属主未初始化（README:206 需手工 `chown 999:999`，**L7**）；`.gitkeep` 占位说明目录已在库中（`docker/mysql/data/.gitkeep`） |
| 时区挂载 | `/etc/localtime:/etc/localtime:ro`（26） | ⚠️ 与 `TZ` 环境变量重复，宿主缺文件会创建目录导致启动失败（**M6**） |
| 网络隔离 | 四个服务同一 `app_network` bridge（217-219） | ⚠️ mysql/redis 与 nginx 同网，缺前后端分层（**M5**） |
| 生产/开发分离 | 仅靠 `DEPLOY_ENV` 注入 backend 的 `ENVIRONMENT`（95,102）；开发热更新挂载已注释（123-127）；无 profile、无独立 override 文件 | ⚠️ 分离靠一个变量，无 `docker-compose.override.yaml`/`profiles` 机制（**M4/M5** 一并改造） |
| 镜像 tag | `mysql:8.0`、`redis:7-alpine`、`nginx:1.25-alpine`、`python:3.12-slim` 均浮动（13,53,164；Dockerfile:2） | ❌ **M4** |
| 平台 | 四服务均强制 `platform: linux/amd64`（15,55,98,166） | ℹ️ 生产若为 x86_64 无影响；在 ARM 宿主上会走 qemu 模拟（性能差、mysql 可能起不来），换 ARM 机器时需删掉 |
| 上传目录 | `./backend/static/upload:/home/static/upload`（130） | ✅ 必要（`setting.py:211` `UPLOAD_FILE_PATH=Path("static/upload")`，容器 CWD 为 `/home`，路径对得上）；注意这是 `docker/backend/static/upload`，由 `deploy.sh:41` 创建 |

### 3.2 Dockerfile 与 .dockerignore

`docker/backend/Dockerfile`（26 行）逐项：

| 审计项 | 结论 |
|--------|------|
| 多阶段构建 | ❌ 单阶段。Python 场景收益有限，**不是**必须修项；但见下"体积" |
| 基础镜像固定版本 | ❌ `python:3.12-slim`（第 2 行）浮动 tag，无 digest（**M4**） |
| root 运行 | ❌ 无 `USER`（**H7**） |
| 依赖安装与缓存层 | ⚠️ 思路正确（先 COPY 清单再装，第 13-17 行），但**层顺序错误导致构建失败**（**B2**）；且 `COPY ./backend/ .` 会把 22 MiB 的 `backend/dist` 一起进层（**L3**） |
| pip 源可替换性 | ❌ 硬编码 `-i https://pypi.tuna.tsinghua.edu.cn/simple`（第 17 行），无 `ARG`（**L5**） |
| 镜像体积 | ⚠️ `--no-cache-dir` 已用；但包含 `backend/dist`（22 MiB）、`backend/static/swagger/**/*.map`、`backend/tests`、`backend/sql`；且 `pip install -r requirements.txt` 装**全部三种数据库驱动 + 全部三种对象存储 SDK**（`backend/requirements.txt`），而生产只用 MySQL（`crypto`/`paramiko`/`boto3`/`esdk-obs`/`aliyun`/`cos` 体量可观） |
| 安全基线 | ❌ 无 `HEALTHCHECK`（第 25 行只有 `CMD`），无 `--no-new-privileges` 等（配合 compose，**H7**） |
| 时区/环境 | ⚠️ 第 8 行 `ENV TZ Asia/Shanghai` 用空格分隔（旧式语法，可用但不推荐）；缺 `PYTHONUNBUFFERED` |
| 端口/启动 | ✅ `EXPOSE 8001`、`CMD ["python","main.py","run","--env=prod"]` 为 exec 形式（正确） |

`.dockerignore`（58 行）逐项：**已正确排除** `.venv`(17)、`.git`(31)、`logs`(36)、`*.log`(37)、`frontend`(44)、`backend/static/upload`(58)、各类缓存(11-13,7-9)。
**应排除而未排除**：`backend/env/.env.prod`/`.env.dev`（**B3**）、`docker/`（含私钥，**H6**）、`backend/dist`（**L3/L4**）、`backend/tests`、`.agent-teams`、`docker/nginx/ssl/**`、`*.zip`。
**注意不要排除**：`backend/data/ip2region/**`（`path_conf.py:31-32` 运行时依赖）、`backend/static/swagger/**` 的 js/css（`setting.py:228-230` 的 Swagger/ReDoc 资源）、`backend/sql/**` 与 `backend/templates/**`（初始化种子与代码生成模板）。

### 3.3 nginx（`docker/nginx/nginx.conf`，142 行）

| 审计项 | 结论 |
|--------|------|
| 反代路径 | ✅ **正确**。`location /api/v1 { proxy_pass http://backend:8001; }`（116-128）不带 URI 部分，原样透传 `/api/v1/...`；FastAPI 侧 `root_path="/api/v1"`（`setting.py:311`）会把 `scope["root_path"]` 剥掉再匹配路由（`fastapi/applications.py:1160-1163` → `starlette/_utils.py:90-98` → `starlette/routing.py:255`），所以后端内部按 `/system/...`、`/monitor/...` 注册也能命中。compose 健康检查用的 `/api/v1/monitor/health/check`（`docker-compose.yaml:142`）与此一致。 |
| 上传大小限制 | ⚠️ 仅 http 级 `client_max_body_size 50m`（30 行），与应用 `MAX_FILE_SIZE=10MB`（`setting.py:223`）不匹配（**M10**） |
| gzip | ⚠️ 已开启（42-56），级别 6；缺 `gzip_static`、缺 `application/wasm`，字体已压缩无妨（**M8** 一并优化） |
| SSL 证书处理 | ⚠️ 证书与私钥匹配、未过期（实测），但无 OCSP stapling、无 `ssl_session_tickets off`、无续期机制（**H4/M7**） |
| 安全响应头 | ⚠️ 有 `X-Frame-Options`/`X-Content-Type-Options`/`X-XSS-Protection`/`Referrer-Policy`（60-63）；**缺 HSTS、CSP、Permissions-Policy**，且 `X-XSS-Protection` 已废弃（**M7**）。因 location 块内未再定义 `add_header`，http 级头可正常继承到各 location。 |
| SPA history 回退 | ✅ `/`（99）、`/web`（105）、`/app`（112）都有 `try_files ... /index.html`；`deploy-artifacts.sh` 的注释也记录了"少一层就 500 内部重定向死循环"的坑 |
| 限流 | ✅ `api_limit 30r/s burst=60 nodelay` + `conn_limit 100`（67-69,117-118）只作用于 `/api/v1` |
| 日志 | ⚠️ `access_log ... buffer=32k flush=5s`（39）；第 8 行注释称"错误日志输出到 stdout"，第 9 行实际写 `/var/log/nginx/error.log`——官方镜像里该路径是 `/dev/stderr` 的软链，因此效果上仍进容器日志，但注释与代码不一致，且 buffer 会丢失崩溃前最后 5 秒 |
| 匹配过宽 | ❌ `location /web`（103）会匹配 `/webxxx`；`/app`（110）、`/api/v1`（116）同理（**M9**） |
| WebSocket | ⚠️ 对所有 `/api/v1` 请求无条件设置 `Connection "upgrade"`（131-133），普通 HTTP 请求也带升级头（**M9**） |
| 文档暴露 | ⚠️ `FASTAPI_CONFIG` 关闭了内置 docs（`setting.py:309-310` `docs_url/redoc_url=None`），但 `app/__init__.py:118-119` 的 `register_docs(app)` 无条件注册自定义 `/docs`、`/redoc`。经上面的 root_path 剥离规则，外部可通过 `https://域名/api/v1/docs` 访问 Swagger UI，而 `nginx.conf:116` 对 `/api/v1` 不做任何限制。**建议**：nginx 层显式 `location ~ ^/api/v1/(docs|redoc|openapi\.json)$ { return 404; }`（或加 IP 白名单），或让后端按 `DEBUG` 决定是否注册 docs。 |
| 静态资源缓存 | ❌ 无任何 `Cache-Control`/`expires`（全文件 grep 无命中），而 `docker/nginx/web/dist/js/` 下是带内容 hash 的 immutable 资源（**M8**） |
| error_page | ✅ `500 502 503 504 → /50x.html`（137-140），路径落在镜像自带的 `/usr/share/nginx/html/50x.html`（未被挂载覆盖，因为只挂了子目录） |

### 3.4 deploy.sh（161 行）

见 **H8**（成功误报/无备份/全站重建/trap）、**M2**（compose 命令不一致）、**M12**（无可观测性）、**M13**（`.env` eval 与占位口令）、**L7**（属主）。补充：

- ✅ 优点：`set -euo pipefail`（第 2 行）；彩色分级日志（12-22）；`check_deps` 建目录 + 检查命令（40-55）；`check_code` 校验关键文件（57-67）；`cleanup` 注释里明确写了"`-a` 会删掉服务器上其他项目的未使用镜像，慎用"（117）——这条自我约束是对的。
- ⚠️ `--build-frontend` / `--skip-frontend` 等 README 承诺的参数在 `case` 里没有分支（143-161），会落到 `*) full_deploy "$@"`（160），**被静默忽略**并执行完整部署。
- ⚠️ 幂等性：可重复执行，但每次都会重建全部容器（78 行），且不校验当前是否已经有更新版本在跑。
- ⚠️ 无失败回滚：`build_image`（69-74）失败会 `exit 1`（好）；但 `start_service`（76-88）失败后的处理路径缺失健康门禁（坏）。

### 3.5 deploy-artifacts.sh（未纳入版本管理，但是更成熟的路径）

- ✅ 设计明显优于 `deploy.sh`：本地构建成品 → 服务器不跑构建；`push_dir` 先解包到 `/tmp/fa-stage` 校验 `index.html` 与非空 → 备份旧目录 → 原子替换 → `chown`（`push_dir` 函数体）；后端镜像 `docker save | gzip | ssh docker load`；切换前 `docker tag backend:3.0.0 backend:prev` 保留回滚点；`rollback web|app|backend` 与 `prune` 轮转（备份每标签 5 份、镜像每类 2 份）；`verify` 探测公网四端 HTTP 200；构建时剔除 `OPENAI_*` 并把数据库/Redis 地址强制回 `localhost`（避免把开发凭据烤进镜像——与 **B3** 正好相反，做得对）。
- ❌ 问题：
  1. **未提交**（`git ls-files deploy-artifacts.sh` 为空，`git status` 显示 `??`）→ 真正的生产部署脚本会随工作区清理而丢失，团队其他人无法复现部署。
  2. 硬编码生产 IP 与 root 登录：`SERVER="${FA_SERVER:-8.137.99.5}"`、`ssh_do ... "root@${SERVER}"`、固定 `KEY="$HOME/.ssh/id_ed25519"`（脚本 46-53 行附近）→ 应改为必填环境变量 + 专用部署用户（`sudo` 只放开 docker）。
  3. 只有一个 `backend:prev` 回滚点，连续两次部署后回滚能力退化。
  4. 无数据库备份/回滚（只有静态目录与镜像），schema 变更仍不可逆。
  5. 备份是 `cp -a` 全量复制，无校验和校验（`tar | ssh` 中断可能得到不完整内容，虽 `set -e` 能兜住大部分）。

### 3.6 CI

`\.github/workflows/` 为空 → **无 CI**（**H5**）。这直接影响本轮审计的可信度：**没有任何自动步骤会在合并前发现 B2 这种"镜像构建必然失败"的问题**。

### 3.7 生产环境变量清单（compose 未注入 → 落到默认值）

| 变量 | compose 是否注入 | 默认值 / 实际来源 | 风险 |
|------|------------------|-------------------|------|
| `SECRET_KEY` | ❌ | `setting.py:66` 公开默认值 | **blocker（B1）** |
| `DATA_ENCRYPTION_KEY` | ❌ | `None` → 由 `SECRET_KEY` HKDF 派生（`crypto_util.py:49-52`） | **blocker（B1）** |
| `OPENAI_API_KEY` | ❌ | 镜像内 `backend/env/.env.prod`（真实 key） | **blocker（B3）** |
| `PROD_CORS_ORIGINS` | ❌ | 空 → `ALLOW_ORIGINS` 返回 `["*"]`（`setting.py:243-248`），且 `ALLOW_CREDENTIALS=True`（第 60 行） | high（同源部署下影响有限，但属于错误的生产配置） |
| `SCHEDULER_ALLOW_CODE_EXEC` | ❌ | `True`（`setting.py:127`），注释写着"生产环境强烈建议设为 False" | high（定时任务可执行用户提交的代码块） |
| `ALLOWED_HOSTS` | ❌ | 硬编码 `service.fastapiadmin.com` 等（`setting.py:186`），换域名即全站 400 | medium（**M14**） |
| `TRUSTED_PROXY_HOPS` | ❌ | `1`（`setting.py:34`） | medium（**H2**） |
| `DEMO_ENABLE` | ❌ | `.env.prod` 设 `True` | medium |
| `WORKERS` | ❌ | `1`（`setting.py:33`） | medium（单 worker，注意注释提示 >1 时需确认 Redis jobstore 去重） |
| `DATABASE_*` / `REDIS_*` | ✅ | compose `environment`（104-114）优先于 env_file | ✅ 正确 |

**建议**：新增 `docker/.env.example` 中的 `SECRET_KEY`、`DATA_ENCRYPTION_KEY`、`PROD_CORS_ORIGINS`、`SCHEDULER_ALLOW_CODE_EXEC`、`TRUSTED_PROXY_HOPS` 键位，并在 compose 中用 `${VAR:?}` 强制必填，让"忘记配置"变成启动即失败而不是静默降级。

### 3.8 文档一致性（`docker/README.md`）

| README 声明 | 实际 | 影响 |
|-------------|------|------|
| `:93-103` 支持 `--build-frontend`/`--skip-frontend`、`BUILD_WEB=true` | `deploy.sh:143-161` 无对应分支，未知参数被 `*)` 吞掉执行完整部署 | ⚠️ 误导，运维会以为跳过了前端构建 |
| `:63` `NGINX_SERVER_NAME` 变量（默认 `service.fastapiadmin.com`） | `nginx.conf` 与 compose 中都不存在该变量（grep 无命中），域名在 `nginx.conf:75,83` 硬编码 | ⚠️ 换域名时按文档改 `.env` 无效 |
| `:87` "停止旧容器 → 更新代码 → 构建镜像" | `deploy.sh:5-6` 明确不再拉取代码 | ⚠️ |
| `:219-221` "`./deploy.sh` 自动拉取最新代码" | 同上是错的 | ⚠️ 会造成"部署了但代码没更新"的误判 |
| `:132-135` Swagger 在 `https://域名/docs`、健康检查在 `/health` | `/` 被 `nginx.conf:96-100` 指向 VitePress 官网；Swagger 实际在 `/api/v1/docs`；健康检查实际是 `/api/v1/monitor/health/check` | ⚠️ 验收地址全错 |
| `:138` "docs 和 app 默认不参与部署，需取消注释启用" | `docker-compose.yaml:176-177` 与 `nginx.conf:110` 都是**启用**状态 | ⚠️ 与实际镜像挂载不一致 |
| `:136` 默认账号 `admin/123456` | 需与种子数据核对（`backend/sql/sys_user.json`），属后端范围 | ℹ️ 生产必须改 |
| `:211-215` 安全建议（改默认密码、限制端口） | 仅文档，compose 默认值未落实（H1） | ⚠️ 建议改成默认安全 |

### 3.9 值得肯定的部分（避免只报问题）

1. `docker-compose config` 通过，必填变量用 `${VAR:?错误: ...}` 表达，缺变量即报错并给中文提示（18,21,66 行）。
2. 四个服务都有 healthcheck，backend→mysql/redis 使用 `service_healthy`，比多数项目的 `service_started` 更严谨（131-135）。
3. 日志滚动、内存/CPU 限制、时区、上传目录持久化（130 行注释点明了"不挂载会丢用户上传文件"）都想到了。
4. `.gitignore` 正确排除了 `docker/.env`、`docker/nginx/ssl/*`、三个前端 `dist`，实测 `git ls-files docker/` 无任何密钥入库。
5. nginx `proxy_pass` 与后端 `root_path` 的配合是对的（3.3 已证明）。
6. `deploy-artifacts.sh` 的备份→原子替换→回滚→轮转链路设计完整，且主动剥离 `OPENAI_*`，说明团队已识别部分风险——只是没回流到 `docker/backend/Dockerfile`。
7. 证书与私钥配套、未过期（实测），`ssl/` 以 `:ro` 挂载（175 行）。

---

## 4. 从零到上线部署步骤草案（含证书与备份）

> 前提：先修完第 2 节的 B1/B2/B3 + H1/H8。以下命令在服务器上以部署用户执行，`$DOMAIN` = 实际域名。

### 阶段 0：服务器与网络前置

1. 服务器：≥4 vCPU / 8 GB 内存 / 100 GB 磁盘（compose 限制合计约 2.8 GB，留出 MySQL 数据增长与备份空间）。
2. 安装 Docker Engine ≥ 24 与 **Compose v2 插件**（`docker compose version` 必须成功；不要只装独立版 `docker-compose`）。
3. 云安全组 / 主机防火墙：**入方向只放行 80、443 与 SSH**；3306、6379、8001 一律拒绝。
4. 域名 A 记录指向服务器公网 IP，确认备案/HTTPS 可用。

### 阶段 1：代码与权限

```bash
sudo mkdir -p /home/FastapiAdmin && sudo chown "$USER" /home/FastapiAdmin
# 上传代码（scp / git）
cd /home/FastapiAdmin
chmod 700 docker/nginx/ssl
find docker/nginx/ssl -name '*.key' -exec chmod 600 {} +
```

### 阶段 2：生成密钥与 `.env`

```bash
cp docker/.env.example docker/.env
SECRET_KEY=$(openssl rand -hex 32)
DATA_ENCRYPTION_KEY=$(openssl rand -hex 32)
MYSQL_ROOT_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' )
MYSQL_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' )
REDIS_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' )
# 写入 docker/.env（含 SECRET_KEY / DATA_ENCRYPTION_KEY / PROD_CORS_ORIGINS / SCHEDULER_ALLOW_CODE_EXEC=false）
# 用编辑器填写，避免命令历史留痕：
${EDITOR:-vi} docker/.env
chmod 600 docker/.env
```

必须显式确认的键（对照 3.7）：`SECRET_KEY`、`DATA_ENCRYPTION_KEY`、`MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD`、`REDIS_PASSWORD`、`DEPLOY_ENV=prod`、`SCHEDULER_ALLOW_CODE_EXEC=false`、`PROD_CORS_ORIGINS=https://$DOMAIN`。

### 阶段 3：配置校验（不启动容器）

```bash
cd docker
docker compose config -q && echo "compose OK"
# 显式确认没有以占位口令通过
grep -qE 'your_(mysql|redis)' .env && { echo "❌ 仍是占位口令"; exit 1; } || echo ".env OK"
docker compose config | grep -E 'host_ip|published'   # 人工确认没有 0.0.0.0 的 3306/6379/8001
```

### 阶段 4：构建（带版本 tag 与回滚点）

```bash
cd docker
export DOCKER_BUILDKIT=1
TAG="$(date +%Y%m%d-%H%M%S)"
docker compose build backend                 # 修完 B2 后必须成功
docker tag backend:3.0.0 "backend:${TAG}"
docker tag backend:"${TAG}" backend:prev     # 建立回滚点
docker images 'backend:*'
```

### 阶段 5：证书

```bash
# 方案 A：CA 签发
cp /path/to/fullchain.pem docker/nginx/ssl/server.pem
cp /path/to/privkey.pem   docker/nginx/ssl/server.key
chmod 600 docker/nginx/ssl/server.{pem,key}

# 方案 B：acme.sh 自动签发 + 自动续期（推荐）
curl https://get.acme.sh | sh -s email=ops@example.com
~/.acme.sh/acme.sh --issue -d "$DOMAIN" --standalone        # 需 80 端口空闲
~/.acme.sh/acme.sh --install-cert -d "$DOMAIN" \
  --key-file       /home/FastapiAdmin/docker/nginx/ssl/server.key \
  --fullchain-file /home/FastapiAdmin/docker/nginx/ssl/server.pem \
  --reloadcmd      "cd /home/FastapiAdmin/docker && docker compose exec nginx nginx -s reload"

# 到期巡检（cron 每天 09:00）
# 0 9 * * * openssl x509 -in /home/FastapiAdmin/docker/nginx/ssl/server.pem -noout -checkend 1209600 \
#   || curl -fsS "https://<告警 webhook>" -d "证书 14 天内到期"
```

（同时按 H4 在 `nginx.conf` 的 80 端口 server 里加 `location /.well-known/acme-challenge/` 例外。）

### 阶段 6：分层启动（不要一把梭）

```bash
cd /home/FastapiAdmin/docker
docker compose up -d mysql redis
until [ "$(docker inspect -f '{{.State.Health.Status}}' mysql)" = healthy ] \
   && [ "$(docker inspect -f '{{.State.Health.Status}}' redis)" = healthy ]; do sleep 3; done

docker compose up -d backend
until [ "$(docker inspect -f '{{.State.Health.Status}}' backend)" = healthy ]; do sleep 5; done

docker compose up -d nginx
docker compose ps
```

首次启动时后端会自动完成建表与种子数据（`backend/app/__init__.py:30` → `backend/app/scripts/initialize.py:50-86`：空库 `create_all` + `stamp head`，非空库 `alembic upgrade head`）。
`docker/mysql/init` 目录为空（**L1**），不要期待 MySQL 容器初始化任何 SQL；若需手工导入 `backend/sql/*.json` 之外的 SQL，放在这里或走应用初始化。

### 阶段 7：备份（上线前先建好，别等出事）

```bash
mkdir -p /home/FastapiAdmin/backups
cat > /home/FastapiAdmin/backup.sh <<'EOF'
#!/bin/bash
set -euo pipefail
cd /home/FastapiAdmin/docker
set -a; source .env; set +a
STAMP=$(date +%Y%m%d-%H%M%S)
OUT=/home/FastapiAdmin/backups

docker compose exec -T mysql sh -c \
  'exec mysqldump --single-transaction --routines --triggers --default-character-set=utf8mb4 -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip -1 > "$OUT/db-$STAMP.sql.gz"

tar -czf "$OUT/nginx-$STAMP.tgz" nginx/web/dist nginx/app nginx/docs nginx/nginx.conf
cp .env "$OUT/env-$STAMP"
cp -a redis/data "$OUT/redis-$STAMP" 2>/dev/null || true

# 保留最近 14 天
find "$OUT" -maxdepth 1 -name 'db-*'   -mtime +14 -delete
find "$OUT" -maxdepth 1 -name 'nginx-*' -mtime +14 -delete
find "$OUT" -maxdepth 1 -name 'redis-*' -mtime +14 -delete
echo "backup done: $STAMP"
EOF
chmod +x /home/FastapiAdmin/backup.sh
/home/FastapiAdmin/backup.sh                # 立即跑一次验证可执行

# cron：每天 02:30
# 30 2 * * * /home/FastapiAdmin/backup.sh >> /home/FastapiAdmin/backups/cron.log 2>&1
```

**恢复演练（每季度做一次，否则备份等于没有）**：

```bash
# 1) 停后端（避免写入竞争），保留 MySQL
docker compose stop backend
# 2) 恢复
gunzip -c /home/FastapiAdmin/backups/db-<STAMP>.sql.gz | \
  docker compose exec -T mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'
# 3) 起后端并验证
docker compose start backend
docker compose exec -T backend python -c "import urllib.request;urllib.request.urlopen('http://localhost:8001/api/v1/monitor/health/check',timeout=5);print('health OK')"
```

### 阶段 8：上线验收（每条都要有明确通过标准）

```bash
D=https://$DOMAIN
curl -sS -o /dev/null -w 'root      %{http_code}\n' "$D/"
curl -sS -o /dev/null -w 'web       %{http_code}\n' "$D/web/"
curl -sS -o /dev/null -w 'app       %{http_code}\n' "$D/app/"
curl -sS -o /dev/null -w 'apihealth %{http_code}\n' "$D/api/v1/monitor/health/check"
curl -sS -o /dev/null -w 'swagger   %{http_code}\n' "$D/api/v1/docs"   # 期望 404/403，若 200 则按 3.3 在 nginx 封掉
curl -sSI "$D/" | grep -iE 'strict-transport-security|content-security-policy'  # 期望有命中（修完 M7 后）
echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null | openssl x509 -noout -dates
docker compose ps          # 期望四服务 Up (healthy)
# 端口暴露复核（应从外部超时/拒绝）
nc -z -w3 <公网IP> 3306; nc -z -w3 <公网IP> 6379; nc -z -w3 <公网IP> 8001
```

### 阶段 9：日常发布与回滚

```bash
# 发布（推荐用 deploy-artifacts.sh，先把它提交进仓库并按 M15 去掉硬编码 IP）
./deploy-artifacts.sh web
./deploy-artifacts.sh app
./deploy-artifacts.sh backend      # 内部已含备份点/镜像 tag/健康轮询

# 回滚
./deploy-artifacts.sh backups
./deploy-artifacts.sh rollback web
./deploy-artifacts.sh rollback app
./deploy-artifacts.sh rollback backend
```

⚠️ **回滚边界**：镜像回滚不会反向执行数据库迁移。若某次发布包含 schema 变更（`alembic upgrade`），回滚必须同时恢复阶段 7 的数据库备份，并把后端一并停掉避免双写；上线含 schema 变更的版本前务必手工跑一次 `backup.sh`。

### 阶段 10：可观测性最小集

- 容器健康：`docker compose ps` + `docker events` 接告警（`restart` 事件）。
- 磁盘：`df -h` 对 `/` 与数据卷目录做阈值告警（MySQL 数据 + 日志 + 备份三处）。
- 证书：阶段 5 的 `-checkend` 巡检。
- 应用：nginx access/error 日志（`docker compose logs nginx`）5xx 比例；后端日志在 `backend/logs`（已挂载？当前 compose **未**挂载 `backend/logs`，容器内日志文件随容器销毁而丢失，只有 stdout 被 `json-file` 驱动轮转保留 —— 如需长期留存建议加挂载或接日志采集）。

---

## 5. 建议的处理顺序（给排期用）

1. **当天**（不改业务代码即可完成）：B1 注入并轮换密钥 → B3 排除/轮换泄露凭据 → H3 收紧权限 → H1 收敛端口。
2. **本周**：B2 修 Dockerfile 层顺序（否则任何人都无法构建镜像）→ H8 给 `deploy.sh` 加备份/健康门禁/回滚 → H5 建最小 CI（compose config + docker build + pytest）。
3. **两周内**：H4 证书自动化与到期告警 → H6 精简构建上下文 → H7 非 root + 容器安全基线 → M1/M3/M4/M11。
4. **可排期**：M7/M8/M9/M10 的 nginx 加固与性能项 → M2/M12/M13/M15 部署脚本工程化 → L1/L2 文档与注释纠偏。

---

## 6. 与其它审计角色的边界

本报告只覆盖容器与部署链路。以下发现虽在部署过程中被确认，但根因属后端代码/配置域，建议由对应负责人并入主清单：

- `setting.py:127` `SCHEDULER_ALLOW_CODE_EXEC=True`（远程代码执行面）与 `setting.py:243-248` 生产 CORS 回落 `["*"]`；
- `setting.py:66` 注释与实现不符（注释称必填、实现有默认值），以及 `backend/tests/conftest.py:32` 用环境变量兜底证明"必填"是设计意图；
- `app/__init__.py:118-119` 无条件注册 `/docs`、`/redoc`（生产是否应暴露需产品决策）；
- `backend/app/__init__.py:127-129` `app.frontend("/")` 的 catch-all 与 JSON 404 语义冲突。

## 7. 复现本审计的方法

```bash
cd /Users/tao/workspace/FastapiAdmin

# 组件版本
docker version            # Client 29.8.0 (context: colima) / Server 29.5.2
docker compose version    # ❗ 本机报 "unknown command: docker compose"
docker-compose --version  # Docker Compose version 5.5.1（homebrew 独立版）
docker buildx version     # ❗ 本机报 "unknown command: docker buildx"

# compose 静态校验（未启动容器）
cd docker && docker-compose config ; echo "exit=$?"    # exit=0
docker-compose config | grep -c host_ip                # 0 —— 无任何端口限定到 127.0.0.1

# Dockerfile 依赖层顺序（静态判定，未构建）
sed -n '13,21p' ../docker/backend/Dockerfile

# 证书有效期 / 配套性
openssl x509 -in nginx/ssl/server.pem -noout -subject -issuer -dates
openssl x509 -in nginx/ssl/server.pem -noout -pubkey | openssl md5
openssl rsa  -in nginx/ssl/server.key -pubout 2>/dev/null | openssl md5

# 权限
ls -l nginx/ssl/server.key .env

# 入库情况（确认密钥未提交）
git ls-files docker/ | grep -v -E '^docker/nginx/(web|docs|app)/'
git ls-files backend/requirements/     # 空 → 依赖拆分未提交（B2 的成因之一）

# CI
ls -laR ../.github/

# 构建上下文体积（按 .dockerignore 规则静态统计）
python3 - <<'PY'
import os
root='/Users/tao/workspace/FastapiAdmin'
ig={'.git','frontend','.venv','node_modules','logs','.ruff_cache','.mypy_cache','.pytest_cache','__pycache__','.vscode','.idea','.codebuddy','.workbuddy','.agent-teams'}
t=0
for dp,dns,fns in os.walk(root):
    dns[:]=[d for d in dns if d not in ig]
    if 'static' in dp.split(os.sep) and 'upload' in dp.split(os.sep): dns[:]=[]; continue
    for f in fns:
        if f.endswith(('.pyc','.pyo','.pyd','.log','.db','.sqlite3')) or f in ('.DS_Store','.gitignore','.gitattributes'): continue
        try: t+=os.path.getsize(os.path.join(dp,f))
        except OSError: pass
print(f"approx context = {t/1024/1024:.1f} MiB")
PY
# → approx context = 68.4 MiB
```

**未执行**（受本轮只读约束）：`docker build`、`docker compose up/down`、`nginx -t`、任何容器启动、依赖安装、git 提交。因此 `nginx.conf` 的语法正确性只做了静态审查（`docker-compose config` 校验的是 compose 而非 nginx.conf）。

**证据时效说明**：审计期间工作区被多个并行审计成员同时读写，`backend/uv.lock`、`docker/.env.example`、`backend/requirements.txt` 在本报告定稿前发生过变化（非本任务所为）。所有关键结论（B1/B2/B3 的引用内容、compose/Dockerfile/nginx.conf 的原始行号、证书与权限实测值）已在定稿前逐条复核，仍然成立；若后续再修改这些文件，请以“文件内容”而非行号为准。

## 8. 实测输出存档

| 命令 | 关键输出 |
|------|---------|
| `docker version` | Client `Docker Engine - Community 29.8.0`（darwin/arm64，Context: colima）；Server `29.5.2`（linux/arm64，overlayfs，Cgroup v2） |
| `docker compose version` | `docker: unknown command: docker compose`（`~/.docker/cli-plugins/docker-compose` 软链指向 `/Applications/Docker.app/...`，目标不存在） |
| `docker-compose version` | `Docker Compose version 5.5.1`（`/opt/homebrew/bin/docker-compose`） |
| `docker buildx version` | `docker: unknown command: docker buildx` |
| `docker info` | Containers 0 / Images 23 / Logging Driver json-file / Cgroup Version 2 |
| `cd docker && docker-compose config` | 退出码 **0**；输出含 `name: docker`、backend `platform: linux/amd64`、`image: backend:3.0.0`、`FORWARDED_ALLOW_IPS: '*'`、mysql healthcheck 中口令被展开为明文；`grep -c host_ip` = **0** |
| `openssl x509 -in docker/nginx/ssl/server.pem -noout -subject -issuer -dates` | `subject= /CN=service.fastapiadmin.com`；`issuer= /C=PL/O=Asseco Data Systems S.A./CN=Certum DV TLS G2 R39 CA`；`notBefore=Aug 19 14:10:22 2026 GMT`；`notAfter=Mar 6 14:10:21 2027 GMT`；SAN `DNS:service.fastapiadmin.com`；`-checkend 0` → not expired |
| 证书/私钥配套性 | `server.pem`、`service.fastapiadmin.com/nginx/*.crt`、`.../pem/*.pem` md5 均为 `f308d6601a5521014d9a4b205c89efeb`；`server.pem` 公钥 md5 与 `server.key` 公钥 md5 一致（`4d0165b5c7a158d519cd29fd6a6f699a`） |
| `ls -l` | `docker/.env` 0644；`docker/nginx/ssl/server.key` 0666；`.../nginx/*.key` 0666；`iis/password.txt`、`tomcat/password.txt` 各 6 字节 |
| `git ls-files docker/`（滤除前端产物） | 仅 `.env.example`、`README.md`、`Dockerfile`、`docker-compose.yaml`、`mysql/.gitkeep`、`mysql/data/.gitkeep`、`mysql/init/.gitkeep`、`nginx.conf`、`nginx/ssl/.gitkeep`、`redis/.gitkeep`、`redis/conf/redis.conf`、`redis/data/.gitkeep` —— **无 `.env`、无证书** |
| `git ls-files backend/requirements/` | 空（`git status`：`?? backend/requirements/`） |
| `ls -laR .github/` | `workflows/` 空目录，`total 0` |
| 上下文体积静态统计 | **68.4 MiB**；Top 项：`backend/data/ip2region/ip2region_v4.xdb` 10.61 MiB、`docker/nginx/web/dist/js/iconify-icons.*.js` 2.55 MiB、`backend/dist/js/iconify-icons.*.js` 2.55 MiB、`backend/static/swagger/redoc/bundles/redoc.standalone.js.map` 2.55 MiB；`docker/nginx/ssl/**` 命中 **21** 个文件 |
| 目录体积 | 仓库总计 2.0 G（`.git` 151 M、`backend/.venv` 231 M、`frontend` 1.5 G、`docker/nginx` 28 M、`backend/dist` 22 M、`backend/data` 11 M、`backend/logs` 6.5 M） |
| 源码判定 | `backend/app/config/setting.py:311` `root_path=/api/v1` → `backend/.venv/.../fastapi/applications.py:1160-1163` 设置 `scope["root_path"]` → `starlette/_utils.py:90-98` + `starlette/routing.py:255` 在匹配前剥离 → nginx 的 `proxy_pass http://backend:8001;`（不重写 URI）**正确** |

---

*报告结束。本轮为只读审计，除本文件外未修改、未删除任何仓库文件，未构建、未启动任何容器，未提交 git。*
