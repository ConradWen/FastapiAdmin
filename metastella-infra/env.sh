# MetaStella 项目环境净化（E-5）
# 背景：~/.bashrc source ~/dev_env/env.sh（sksj 项目），向每个 shell 注入
# NODE_OPTIONS/DB_PASSWORD/SPRING_*/Java 路径（AGENTS.md 环境隐患登记）。
# 用法：进入工程 shell 后 `source env.sh`；或经 ./devshell 起净化后的交互 shell。
# 纪律：只清理、不新增；不动 ~/.bashrc 本体（sksj 仍需要它）。

unset NODE_OPTIONS
unset DB_PASSWORD

# Spring 系变量整族剔除
while IFS= read -r _v; do
  unset "$_v"
done < <(compgen -e | grep '^SPRING_' || true)

# JDK 路径从 PATH 剔除（uv/venv 走 .venv，不用 JAVA_HOME）
if [ -n "${JAVA_HOME:-}" ]; then
  unset JAVA_HOME
fi
PATH=$(printf '%s' "$PATH" | tr ':' '\n' | grep -v -i -e '/java' -e '/jdk' | paste -sd: -)
export PATH

unset _v 2>/dev/null
echo "[MetaStella env] sanitized: NODE_OPTIONS/DB_PASSWORD/SPRING_*/JAVA_HOME removed"
