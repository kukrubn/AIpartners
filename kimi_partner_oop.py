"""
AI智能伴侣 —— OOP 版（功能全集）
与过程式版 kimi_partner.py 行为完全一致，包含全部新增功能：
  - 模型 / temperature 调节面板（参数随会话独立保存）
  - 上下文滑动窗口 build_context（发送切片，存档完整）
  - API 调用异常处理 + 失败回滚 user 消息
  - 删除会话二次确认（st.dialog）

结构划分（逻辑层用类，界面层保持过程式 —— Streamlit 重跑模型下的标准姿势）：
  ChatSession   一次会话的数据（含 settings）+ 序列化 + system prompt / 上下文组装
  SessionStore  sessions/ 文件夹的读写删（所有碰文件的代码都在这里）
  LLMClient     大模型调用细节（参数、流式解析）对外隐藏
"""

import datetime
import json
import os
import uuid

import openai
import streamlit as st
from openai import OpenAI

print("----------->重新执行此文件，渲染展示页面")

# 可选模型列表（模块级常量，侧边栏下拉框和默认值都用它）
MODEL_OPTIONS = ["deepseek-v4-pro", "deepseek-v4-flash"]


# ============================================================
# 类 1：ChatSession —— 一次会话
# ============================================================
class ChatSession:
    """一次会话：昵称、人设、模型参数、会话名、消息列表，以及围绕它们的操作"""

    # 类属性：所有对象共享的默认值（类似 C++ 的 static 成员变量）
    DEFAULT_NICK_NAME = "花花"
    DEFAULT_IDENTITY = "一个性格傲娇，但是又会认真解答的雌小鬼"
    DEFAULT_MODEL = "deepseek-v4-pro"
    DEFAULT_TEMPERATURE = 1.0

    def __init__(self, nick_name=None, identity=None):
        """构造函数：不传参时给默认人设；传空串表示"要求用户重新填写" """
        self.nick_name = nick_name if nick_name is not None else self.DEFAULT_NICK_NAME
        self.identity = identity if identity is not None else self.DEFAULT_IDENTITY
        self.session_name = self._generate_name()
        self.messages = []
        # 可调参数收进一个字典，跟着会话走（落盘、加载、切换都自动带上）
        self.settings = {
            "model": self.DEFAULT_MODEL,
            "temperature": self.DEFAULT_TEMPERATURE,
        }

    @staticmethod
    def _generate_name():
        """静态方法：不访问 self，类似 C++ 的 static 成员函数。
        时间戳 + 随机后缀，避免同一秒内创建会话时文件名撞车互相覆盖。"""
        return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_" + uuid.uuid4().hex[:6]

    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content})

    def build_system_prompt(self):
        """system prompt 的拼装规则收敛到对象内部，主代码不用关心格式"""
        return f"""
你叫{self.nick_name}
rules:
      {self.identity}
请遵守以上rules.
"""

    def build_context(self, max_turns=40):
        """组装发给 API 的消息列表：system 永远在最前，历史只取最近 max_turns 条。
        返回新列表，不修改 self.messages（发送用切片，存档仍是完整历史）。"""
        window = self.messages[-max_turns:]
        # 窗口边界若切在 assistant 消息上，再丢一条，保证历史以 user 开头
        if window and window[0]["role"] == "assistant":
            window = window[1:]
        return [{"role": "system", "content": self.build_system_prompt()}] + window

    def to_dict(self):
        """序列化：对象 -> dict，供 json.dump 使用（settings 一并落盘）"""
        return {
            "nick_name": self.nick_name,
            "identity": self.identity,
            "settings": self.settings,
            "current_session": self.session_name,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data):
        """类方法 / 工厂函数：dict -> 对象。
        全程 .get() 给默认值，没有 settings 字段的旧存档也能加载。"""
        session = cls(nick_name=data.get("nick_name", ""),
                      identity=data.get("identity", ""))
        session.session_name = data.get("current_session", session.session_name)
        session.messages = data.get("messages", [])
        # 旧存档没有 settings 时保留构造出来的默认值
        session.settings = data.get("settings", session.settings)
        return session


# ============================================================
# 类 2：SessionStore —— 存档管理器
# ============================================================
class SessionStore:
    """sessions/ 文件夹的增删查读。以后换存储介质（JSON -> SQLite）只改这一个类"""

    def __init__(self, folder="sessions"):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)

    def _path(self, session_name):
        """下划线开头 = 约定俗成的"私有方法"，外部不应调用"""
        return os.path.join(self.folder, f"{session_name}.json")

    def save(self, session: ChatSession):
        # 只保存有实际聊天内容的会话，避免产生空文件
        if not session.messages:
            return
        with open(self._path(session.session_name), "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)

    def list(self):
        """返回所有存档名（去掉 .json 后缀），按名称倒序，最新的在前"""
        names = [f[:-5] for f in os.listdir(self.folder) if f.endswith(".json")]
        return sorted(names, reverse=True)

    def load(self, session_name) -> ChatSession:
        """读取存档并还原成 ChatSession 对象。
        文件不存在或损坏时抛 FileNotFoundError / json.JSONDecodeError，由调用方处理"""
        with open(self._path(session_name), "r", encoding="utf-8") as f:
            return ChatSession.from_dict(json.load(f))

    def delete(self, session_name):
        if os.path.exists(self._path(session_name)):
            os.remove(self._path(session_name))


# ============================================================
# 类 3：LLMClient —— 大模型服务
# ============================================================
class LLMClient:
    """封装 DeepSeek API 调用，对外只暴露一个生成器方法 stream_chat()"""

    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com")

    def stream_chat(self, session: ChatSession):
        """生成器（yield）：边收边吐增量文本，调用方逐段渲染。
        模型和 temperature 从会话对象的 settings 里取。
        注意：生成器函数被调用时函数体并不执行，create() 和流式迭代
        都发生在调用方 for 循环驱动期间 —— 所以调用方用一个 try
        包住 for 循环，就能同时覆盖两个阶段。"""
        response = self.client.chat.completions.create(
            model=session.settings["model"],
            temperature=session.settings["temperature"],
            messages=session.build_context(),
            stream=True,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}}
        )
        for chunk in response:
            if not chunk.choices:  # 跳过空 chunk（如用量统计帧），防止 IndexError
                continue
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content


# ============================================================
# 全局对象
# ============================================================

# 存档管理器：构造时会自动建好 sessions/ 文件夹
store = SessionStore()


# 大模型客户端：用缓存，避免每次页面重跑都新建 HTTP 客户端
@st.cache_resource
def get_llm():
    return LLMClient()


llm = get_llm()

# ============================================================
# 页面配置 & 状态初始化
# ============================================================

st.set_page_config(
    page_title="AI智能伴侣",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={}
)

# 会话对象：session_state 里只存这一个对象，取代散落的键
if "session" not in st.session_state:
    st.session_state.session = ChatSession()
session = st.session_state.session

# 侧边栏组件绑定的 key：首次运行时从对象取值做种子
if "nick_name" not in st.session_state:
    st.session_state.nick_name = session.nick_name
if "identity" not in st.session_state:
    st.session_state.identity = session.identity
if "model" not in st.session_state:
    st.session_state.model = session.settings["model"]
if "temperature" not in st.session_state:
    st.session_state.temperature = session.settings["temperature"]


# ============================================================
# 辅助函数：把对象状态同步到组件绑定的 key（回调里调用）
# ============================================================

def sync_widgets_to_session():
    """回调里换了新会话对象后，把对象状态推给各输入组件"""
    st.session_state.nick_name = session_ref().nick_name
    st.session_state.identity = session_ref().identity
    st.session_state.model = session_ref().settings["model"]
    st.session_state.temperature = session_ref().settings["temperature"]


def session_ref():
    """回调执行时 st.session_state.session 可能刚被替换，统一从这里取当前对象"""
    return st.session_state.session


# ============================================================
# 按钮回调（回调在脚本重跑前执行，可以安全地修改组件状态）
# ============================================================

def on_new_session():
    store.save(st.session_state.session)  # 保存旧会话
    # 全新对象：新会话名、空消息、人设清空（要求重填）、参数回默认
    st.session_state.session = ChatSession(nick_name="", identity="")
    sync_widgets_to_session()


def on_load_session(session_name):
    store.save(st.session_state.session)  # 先保存当前正在聊的会话
    try:
        st.session_state.session = store.load(session_name)
    except (FileNotFoundError, json.JSONDecodeError):
        st.toast("会话文件不存在或已损坏", icon="⚠️")
        return
    sync_widgets_to_session()


def on_delete_session(session_name):
    store.delete(session_name)
    # 如果删的是当前会话，重置为全新状态（否则下次自动保存文件会"复活"）
    if st.session_state.session.session_name == session_name:
        st.session_state.session = ChatSession(nick_name="", identity="")
        sync_widgets_to_session()


@st.dialog("确认删除")
def confirm_delete(name):
    """删除二次确认对话框（st.dialog 装饰的函数，调用时以弹窗形式渲染）"""
    st.write(f"确定要删除会话「{name}」吗？此操作不可恢复。")
    col1, col2 = st.columns(2)
    if col1.button("删除", type="primary", width="stretch"):
        on_delete_session(name)
        st.rerun()
    if col2.button("取消", width="stretch"):
        st.rerun()


# ============================================================
# 界面渲染（UI 层保持过程式，是 Streamlit 下的正确姿势）
# ============================================================

st.title("AI智能伴侣")
st.logo("./resources/Kukrushka.jpg")

# 聊天历史显示
for message in session.messages:
    st.chat_message(message["role"]).write(message["content"])

# 侧边栏
with st.sidebar:
    st.subheader("AI控制面板")

    # key 双向绑定：选中值自动写入 st.session_state.model / temperature
    st.selectbox("模型", MODEL_OPTIONS, key="model")
    st.slider("temperature（越高越有创意，越低越稳定）",
              min_value=0.0, max_value=2.0, step=0.1, key="temperature")

    st.button("新建会话", width="stretch", icon="✍️", on_click=on_new_session)

    # 会话历史（倒序，最新的排在上面）
    st.text("会话历史")
    for name in store.list():
        col1, col2 = st.columns([4, 1])
        with col1:
            # 当前正在进行的会话禁点加载
            st.button(name, width="stretch", icon="📖", key=f"load_{name}",
                      on_click=on_load_session, args=(name,),
                      disabled=(name == session.session_name))
        with col2:
            # 删除按钮唤起确认对话框
            if st.button(" ", icon="❌️", key=f"delete_{name}"):
                confirm_delete(name)

    st.subheader("伴侣信息")
    st.text_input("昵称", placeholder="Ta的名字是:", key="nick_name")
    st.text_area("性格（人设）", placeholder="Ta是......", key="identity")

# 把组件的值同步回会话对象（用户操作组件只改了 session_state，对象还没更新）
session.nick_name = st.session_state.nick_name
session.identity = st.session_state.identity
session.settings["model"] = st.session_state.model
session.settings["temperature"] = st.session_state.temperature

# ============================================================
# 对话主流程
# ============================================================

prompt = st.chat_input("请输入您的问题")
if prompt:  # 字符串自动转化为bool值
    # 校验：昵称和人设没填完不允许提问
    if not session.nick_name or not session.identity:
        st.warning("请先在侧边栏填写 Ta 的昵称和性格（人设）哦~")
        st.stop()

    st.chat_message("user").write(prompt)
    print("---------->,调用AI大模型，提示词:", prompt)
    session.add_message("user", prompt)

    try:
        # stream_chat 是生成器：create() 和流式迭代都在这个 for 循环驱动下发生，
        # 所以一个 try 同时覆盖"建立连接"和"流传输"两个阶段
        response_box = st.empty()  # 创建一个空的组件
        full_response = ""
        for delta in llm.stream_chat(session):
            full_response += delta
            response_box.chat_message("assistant").write(full_response)

        # 只有整个流成功完成才追加 assistant 消息并落盘
        session.add_message("assistant", full_response)
        store.save(session)

    except openai.AuthenticationError:
        st.error("API Key 无效，请检查 DEEPSEEK_API_KEY")
        session.messages.pop()  # 回滚：撤掉刚追加的 user 消息
        st.stop()
    except Exception as e:
        st.error(f"出现了问题：{e}，请检查token余额或网络连接")
        session.messages.pop()  # 回滚：撤掉刚追加的 user 消息
        st.stop()