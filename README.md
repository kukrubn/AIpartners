# AI 智能伴侣（基于黑马程序员 AI 伴侣项目的改动版）

一个基于 Streamlit + DeepSeek API 的角色扮演聊天应用。你可以自定义 AI 的昵称和性格（人设），与它进行多轮流式对话，会话自动持久化到本地 JSON 文件。

本项目是在**黑马程序员《AI 智能伴侣》教程项目**的基础上，针对原教程代码中的若干 bug 和工程缺陷进行修改与功能扩展的产物。下文「改动清单」一节明确列出了所有改动点及改动原因。

## 效果预览

- 自定义 AI 昵称与性格人设，system prompt 实时拼装
- 流式输出，逐字渲染
- 多会话管理：新建 / 加载 / 删除（带二次确认），会话自动保存到 `sessions/*.json`
- 侧边栏可调模型与 temperature 参数，参数随会话独立保存
- 上下文滑动窗口，控制 token 开销

## 改动清单（相对黑马教程原版）

### Bug 修复

| # | 改动 | 原版问题 | 修改方式 |
|---|------|---------|---------|
| 1 | 会话名加 UUID 随机后缀 | 会话名只用时间戳，同一秒内新建两次会话，文件名撞车互相覆盖存档 | `generate_session_name()` 追加 `uuid4().hex[:6]` |
| 2 | 恢复空会话守卫 | 原版把 `and st.session_state.messages` 注释掉了，点一次"新建会话"就落盘一个空 JSON | `save_session()` 只在有实际消息时写盘 |
| 3 | 修复"新建会话"在空消息时失效 | 原版重置逻辑包在 `if st.session_state.messages:` 里，消息为空时按钮无任何效果 | 改用 `on_click` 回调（`on_new_session`），回调在脚本重跑前执行，无条件重置 |
| 4 | 加载会话容错 | 原版文件不存在/损坏时静默失败或崩溃，且老存档缺字段会 `KeyError` | `on_load_session()` 捕获 `FileNotFoundError` / `JSONDecodeError` 并 toast 提示；读取统一用 `.get()` 给默认值，兼容旧存档 |
| 5 | 加载前保存当前会话 | 原版直接切换，当前会话未保存的轮次会丢 | `on_load_session()` 先调 `save_session()` |
| 6 | 流式响应防空 chunk | DeepSeek 流式返回末尾可能带空的用量统计帧，`chunk.choices[0]` 会抛 `IndexError` | 迭代时 `if not chunk.choices: continue` 跳过 |

### 工程改进

| # | 改动 | 说明 |
|---|------|------|
| 7 | OpenAI 客户端缓存 | `@st.cache_resource` 装饰 `get_client()`，避免 Streamlit 每次重跑都新建 HTTP 客户端 |
| 8 | 侧边栏输入框改用 `key=` 双向绑定 | 替代原版 `value=` + 手动赋值的写法，消除状态不同步风险 |
| 9 | API 调用异常处理与回滚 | `try/except` 覆盖 `create()` 调用和整个流式迭代；分层捕获 `AuthenticationError` 与通用异常；失败时 `pop()` 回滚已追加的 user 消息，避免留下"问了没回"的半截对话 |
| 10 | 删除会话二次确认 | 删除按钮唤起 `st.dialog` 确认框，防止误删 |
| 11 | 当前会话禁止重复加载 | 加载按钮 `disabled=(session == current_session)` |
| 12 | 人设未填写禁止提问 | 校验昵称/人设非空，否则 `st.warning` + `st.stop()`，防止拼出空白的 system prompt |

### 新增功能

| # | 功能 | 实现 |
|---|------|------|
| 13 | 模型 / temperature 调节面板 | 侧边栏 `st.selectbox` + `st.slider`，`key=` 双向绑定；参数随会话存入 JSON（`model`、`temperature` 字段），切换会话各自恢复，新建会话重置为默认 |
| 14 | 上下文滑动窗口 | 新增 `build_context()` 纯函数：system prompt 永远置顶，历史只取最近 N 条，窗口边界若切在 assistant 消息上则再丢弃一条，保证历史以 user 开头。发送用切片、存档仍保留完整历史 |

## 运行方法

```bash
# 1. 安装依赖
pip install streamlit openai

# 2. 配置 DeepSeek API Key（环境变量）
# Windows PowerShell:
$env:DEEPSEEK_API_KEY="sk-你的key"
# Linux/macOS:
export DEEPSEEK_API_KEY="sk-你的key"

# 3. 启动
streamlit run kimi_partner.py
```

## 目录结构

```
├── kimi_partner.py      # 主程序
├── resources/
│   └── Kukrushka.jpg    # 页面 logo
└── sessions/            # 会话存档（运行时自动生成，*.json）
```

> 提示：建议在 `.gitignore` 中加入 `sessions/`，避免把聊天存档提交到仓库。

## 技术栈

- Python 3.10+
- Streamlit（`st.cache_resource` / `st.dialog` / `key` 双向绑定 / `on_click` 回调）
- OpenAI Python SDK（DeepSeek 兼容接口，流式输出）

## 致谢

感谢黑马程序员的教程项目提供的原始实现与学习思路。
