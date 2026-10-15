# K3 HTML 应用契约

## 必需文件

- `index.html`：页面入口，正确引用本地 `styles.css` 和 `app.js`。
- `styles.css`：响应式布局，桌面最小宽度 1024px 下可用。
- `app.js`：交互逻辑，不依赖外部网络。
- `README.md`：功能、启动命令、验证方法和限制。

可增加 `assets/`、`tests/` 和数据文件，但必须使用相对路径。

## HTML 与交互

- 设置 UTF-8 和 viewport。
- 页面必须有唯一 `h1`、主内容区域和可见的状态/错误反馈。
- 按钮使用语义化 `<button>`，表单控件有 label 或 aria-label。
- 主要交互不能只依赖 hover；键盘焦点必须可见。
- 数据仅需本地保存时使用 `localStorage`，并处理不可用或损坏数据。

## JavaScript

- 使用严格模式或 ES module。
- 不使用 `eval`、`new Function`、动态脚本注入或外部请求。
- 状态更新和 DOM 渲染分离；错误对用户可见，对控制台保留可操作信息。
- 随机行为应支持确定性种子或可复现测试路径。

## K3 运行

在应用目录执行 `python3 -m http.server 8000 --bind 127.0.0.1`，浏览器访问 `http://127.0.0.1:8000/`。不得要求 Node.js 构建或云端服务才能打开首屏。
