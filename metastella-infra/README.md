# MetaStella 平台基建（metastella-infra/）

> **定位**：MetaStella **平台自身**的存储与开发环境基建（ADR-0031 平台自建存储 / ADR-0034 生成物数据库）。
> 与上游 `docker/` 的区别：那是**产品的部署编排**（M4 改造对象）；本目录是**平台开发/运行的自身基建**，血统归 MetaStella。

## 内容

| 文件 | 用途 |
|---|---|
| `docker-compose.yml` | metastella-pg（PG17+pgvector @宿主 55432；隔离纪律：不碰 sksj=5433/6380、foxonto=5432） |
| `.env.example` | 本地开发连接参数（POSTGRES_* 唯一出处） |
| `env.sh` / `devshell` | E-5 环境净化（清除 sksj 污染变量；`./devshell` 起净化交互 shell） |
| `.python-version` | Python 3.12（ADR-0037⑦；uv 钉版载体在 `../backend/uv.lock`） |

## 用法

```bash
cd fba/metastella-infra
docker compose up -d          # 起 metastella-pg
source env.sh                 # 或 ./devshell 起净化 shell
uv run --project ../backend pytest -q   # 97 passed（P-02 证据）
```

> 历史：本目录原在 MetaStella-platform 壳仓（2026-10-04 B' 两仓收敛迁入，用户裁定）。
