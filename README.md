# 基于强化学习的产业链分布式资源适配与调度管控系统

本系统是一个面向产业链协同场景的分布式资源适配与调度管控系统，当前仓库交付形态为：

- Python 求解器能力
- FastAPI 后端
- MongoDB 数据存储
- Vue 3 前端
- 多智能体车间助手

## 快速启动

详细步骤见 **[部署启动.md](docs/部署启动.md)**（含环境配置、知识库、排障）。

```powershell
# 1. 环境与依赖（项目根目录）
python -m venv .\metaforge-test-env --system-site-packages
.\metaforge-test-env\Scripts\Activate.ps1
pip install -r .\requirements.txt
pip install -e . --no-build-isolation --no-deps
pip install flask flask-cors gym==0.26.2

# 2. 配置（复制后填写 API Key）
copy .env.example .env
copy .\rag\langchain-agent\.env.example .\rag\langchain-agent\.env

# 3. 构建前端
cd .\frontend
npm install
npm run build
cd ..

# 4. 启动
Start-Service MongoDB
cd .\tests
python .\main.py
```

启动后访问：

- 主系统：**http://127.0.0.1:8008/new-ui/home**
- 知识库（随主后端自动嵌入 Streamlit；也可手动 `.\scripts\start_rag_streamlit.ps1`）→ `/new-ui/home/knowledge`
- 物流资源管控（集成 `zhenjie` 多周期车辆路径优化，随主后端挂载，无需单独启动）→ `/new-ui/home/logistics-resource/experiment`，侧边栏提供订单管理、实验配置、结果汇总、图表分析和路径地图。

## 核心文档

- [文档索引](docs/README.md)
- [部署启动](docs/部署启动.md)
- [软件说明书](docs/软件说明书.md)
- [功能清单](docs/智能体功能清单.md)
- [产品需求文档](docs/PRD.md)

## 系统能力

- 多算法排程与结果对比
- MES 执行仿真与异常重排
- 交期评估、物料检查、资源协同
- 计划库管理与排程结果落库
- 自然语言驱动的多智能体助手
- 生产资源管控已同步 `earlymessi/metaforge_agent` 的 `V1@08874218`：协同策略工作台、计划包执行、定时异常与方案对比；详见 [同步记录](docs/生产资源管控模块升级对照记录.md)。

## 目录说明

- `src/metaforge/`: 后端核心能力与求解器
- `frontend/`: Vue 3 前端
- `tests/main.py`: 本地后端启动入口
- `docs/`: 精简后的核心交付文档

## License

MIT
