#!/bin/bash
# 需求管理工具 - 启动脚本
# 用法：
#   方式一：DEEPSEEK_API_KEY=sk-xxx ./start.sh
#   方式二：先编辑 .env 填入 Key，再运行 ./start.sh

DIR="$(cd "$(dirname "$0")" && pwd)"

# 自动加载 .env（如果存在）
set -a
[ -f "$DIR/.env" ] && source "$DIR/.env"
set +a

if [ -z "$DEEPSEEK_API_KEY" ]; then
  echo "⚠️  未设置 DEEPSEEK_API_KEY，AI 归并功能将不可用"
  echo "   请在 .env 文件中填入你的 DeepSeek API Key"
fi

cd "$DIR/backend"

echo "📦 安装依赖..."
pip3 install -r requirements.txt -q

echo "🌱 初始化数据库..."
python3 seed.py 2>/dev/null && echo "   数据库初始化完成" || echo "   数据库已存在，跳过"

echo ""
echo "🚀 启动服务..."
echo "   访问地址：http://localhost:8000/dashboard.html"
echo "   按 Ctrl+C 停止"
echo ""

PYTHONIOENCODING=utf-8 python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1
