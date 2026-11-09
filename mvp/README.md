# ETF Rotation MVP

This directory contains a complete, deliberately small ETF rotation pipeline:

1. Load and validate synchronized daily adjusted-close data.
2. Compute momentum, trend, and low-volatility factors.
3. Rank assets cross-sectionally on each rebalance close.
4. Hold the top eligible assets, or cash when none pass the filters.
5. Execute targets on the next bar and charge per-side transaction costs.
6. Export daily results, executed weights, rebalance rankings, and metrics.

## Run the smoke test

The default command uses deterministic synthetic data. It proves the pipeline runs,
but its performance is not investment evidence.

```powershell
python mvp/run_mvp.py
```

On this macOS device, run from the project root with the dedicated Conda environment:

```bash
# macOS 移植：使用项目绝对路径，避免沿用 Windows 的 C:\\ 路径写法。
conda run -n etf-predict-mvp python /Users/tang/Documents/ETF_Predict/mvp/run_mvp.py
```

## Run with real ETF data

```powershell
python mvp/run_mvp.py --data-dir C:\path\to\daily_etf_data --symbols 510300.SH 510500.SH 518880.SH
```

```bash
# macOS 移植：宿主机数据目录使用 POSIX 路径；路径含空格时保留双引号。
conda run -n etf-predict-mvp python /Users/tang/Documents/ETF_Predict/mvp/run_mvp.py --data-dir "/Users/tang/path/to/daily_etf_data" --symbols 510300.SH 510500.SH 518880.SH
```

Accepted inputs are CSV or Parquet files. A per-symbol file should contain a date
column (`trade_date`, `date`, `datetime`, or `timestamp`) and `adj_close` or `close`.
A wide file may contain one date column and one numeric price column per symbol.
Only daily bars are accepted, and the selected symbols must have at least 80% date
overlap. Missing prices are forward-filled for at most three bars and never
back-filled.

Outputs are written to `mvp/output` by default:

- `daily_backtest.csv`
- `executed_weights.csv`
- `rebalance_ranking.csv`
- `metrics.json`
- `dashboard_data.json`

## Nginx dashboard

Generate the latest dashboard data, then start the Nginx container:

```powershell
python mvp/run_mvp.py
docker compose -f mvp/docker-compose.yml up --build -d
```

Open `http://localhost:8080`. The output directory is mounted read-only into
Nginx and writable into the Agent container. Clicking `刷新数据` reruns the MVP
pipeline and updates the shared dashboard snapshot without rebuilding the image.
The header timestamp includes seconds and the button briefly changes to `已更新`
after a successful refresh.

The dashboard also includes a read-only analysis Agent powered by the
[Agno](https://github.com/agno-agi/agno) runtime. Configure any
OpenAI-compatible provider before starting Compose. For example, with DeepSeek
in PowerShell:

```powershell
$env:LLM_API_KEY = "your-api-key"
$env:LLM_BASE_URL = "https://api.deepseek.com"
$env:LLM_MODEL = "deepseek-chat"
docker compose -f mvp/docker-compose.yml up --build -d
```

Agent 回复使用本地打包的开源前端渲染器：

- [marked](https://github.com/markedjs/marked)：Markdown 结构化排版
- [DOMPurify](https://github.com/cure53/DOMPurify)：清洗模型输出，避免 HTML 注入
- [Mermaid](https://github.com/mermaid-js/mermaid)：将 Agent 输出的 Mermaid 代码块渲染为 SVG 图

这些文件在 Dashboard 镜像构建时下载到 `dashboard/vendor`，浏览器运行时不访问外部 CDN。修改渲染代码后需要重新构建 Dashboard 镜像。

The Agent analysis tools only expose bounded, read-only views of `mvp/output`.
The refresh endpoint imports the strategy pipeline solely to regenerate those
outputs; it does not execute trades. When no API key is configured, the dashboard
and refresh endpoint continue to work while the Agent panel shows `未配置模型`.

To stop the dashboard:

```powershell
docker compose -f mvp/docker-compose.yml down
```

Set a different host port with `DASHBOARD_PORT`, for example:

```powershell
$env:DASHBOARD_PORT = "8090"
docker compose -f mvp/docker-compose.yml up --build -d
```

For a development preview on a machine without Nginx or Docker:

```powershell
python -m http.server 8765 --directory mvp
```

Then open `http://localhost:8765/dashboard/?data=/output/dashboard_data.json`.

Run the dependency-free test suite with:

```powershell
python -m unittest discover -s mvp/tests -v
```

The tests require the core Conda dependencies (`numpy` and `pandas`). On this macOS device:

```bash
# macOS 移植：从项目父目录执行，确保 Python 能导入 mvp 包。
cd /Users/tang/Documents/ETF_Predict && conda run -n etf-predict-mvp python -m unittest discover -s mvp/tests -v
```
