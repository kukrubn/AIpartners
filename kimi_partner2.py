import streamlit as st
import datetime
import os
import uuid
from openai import OpenAI
import json
import openai

print("----------->重新执行此文件，渲染展示页面")

st.set_page_config(
    page_title="AI智能伴侣",
    page_icon="🤖",
    layout="wide",
    # 控制侧边栏
    initial_sidebar_state="expanded",
    menu_items={}
)


# 生成会话标识（加随机后缀，避免同一秒内创建会话时文件名撞车互相覆盖）
def generate_session_name():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_" + uuid.uuid4().hex[:6]


# 保存会话信息函数
def save_session():
    # 只保存有实际聊天内容的会话，避免产生空文件
    if st.session_state.current_session and st.session_state.messages:
        # 构建会话数据
        session_data = {
            "nick_name": st.session_state.nick_name,
            "identity": st.session_state.identity,
            "model": st.session_state.model,  # 新增
            "temperature": st.session_state.temperature,  # 新增
            "current_session": st.session_state.current_session,
            "messages": st.session_state.messages
        }

        if not os.path.exists("sessions"):
            os.mkdir("sessions")

        # 加上 .json 后缀，保存为标准的 JSON 文件
        with open(f"sessions/{st.session_state.current_session}.json", "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)


# 加载所有的会话列表
def load_sessions():
    session_list = []
    if os.path.exists("sessions"):
        file_list = os.listdir("sessions")
        for filename in file_list:
            if filename.endswith(".json"):
                session_list.append(filename[:-5])
    return session_list


# 「新建会话」按钮回调（回调在脚本重跑前执行，可以安全地修改组件状态）
def on_new_session():
    save_session()  # 保存旧会话
    st.session_state.messages = []
    st.session_state.current_session = generate_session_name()
    # 清空昵称和人设，让用户重新输入
    st.session_state.nick_name = ""
    st.session_state.identity = ""
    st.session_state.model = "deepseek-v4-pro"
    st.session_state.temperature = 1.0


# 加载历史会话回调
def on_load_session(session_name):
    save_session()  # 先保存当前正在聊的会话
    try:
        with open(f"sessions/{session_name}.json", "r", encoding="utf-8") as f:
            session_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        st.toast("会话文件不存在或已损坏", icon="⚠️")
        return
    st.session_state.messages = session_data.get("messages", [])
    st.session_state.current_session = session_data.get("current_session", session_name)
    st.session_state.nick_name = session_data.get("nick_name", "")
    st.session_state.identity = session_data.get("identity", "")
    st.session_state.model = session_data.get("model", "deepseek-v4-pro")  # 新增
    st.session_state.temperature = session_data.get("temperature", 1.0)  # 新增


# 删除历史会话回调
def on_delete_session(session_name):
    path = f"sessions/{session_name}.json"
    if os.path.exists(path):
        os.remove(path)
    # 如果删的是当前会话，重置为全新状态（否则下次自动保存文件会"复活"）
    if st.session_state.current_session == session_name:
        st.session_state.messages = []
        st.session_state.current_session = generate_session_name()
        st.session_state.nick_name = ""
        st.session_state.identity = ""
        st.session_state.model = "deepseek-v4-pro"
        st.session_state.temperature = 1.0


# 创建与ai大模型交互的客户端对象（用缓存，避免每次页面重跑都新建）
@st.cache_resource
def get_client():
    return OpenAI(
        api_key=os.environ.get('DEEPSEEK_API_KEY'),
        base_url="https://api.deepseek.com")

def build_context(system_prompt,messages,max_turns=40):
    """
        组装发给 API 的消息列表：system 永远在最前，历史只取最近 max_turns 条。
        返回新列表，不修改传入的 messages（纯函数，没有副作用）。
    """
    window=messages[-max_turns:]
    if window and window[0]["role"] == "assistant":
        window = window[1:]
    return [{"role": "system", "content": system_prompt}]+window

@st.dialog("确认删除")
def confirm_delete(name):
    st.write(f"确定要删除会话「{name}」吗？此操作不可恢复。")
    col1, col2 = st.columns(2)
    if col1.button("删除", type="primary", width="stretch"):
        on_delete_session(name)
        st.rerun()
    if col2.button("取消", width="stretch"):
        st.rerun()


client = get_client()

# 大标题
st.title("AI智能伴侣")
# logo
st.logo("./resources/Kukrushka.jpg")

# 系统提示词
system_prompt = """
你叫%s
rules:
      %s
请遵守以上rules.
"""
# 可选模型列表
MODEL_OPTIONS = ["deepseek-v4-pro", "deepseek-v4-flash"]


# 初始化聊天信息
if 'messages' not in st.session_state:
    st.session_state.messages = []

# 昵称（首次运行给默认值；点击新建会话后会被清空，要求重新填写）
if 'nick_name' not in st.session_state:
    st.session_state.nick_name = "花花"

# 人设
if 'identity' not in st.session_state:
    st.session_state.identity = "一个性格傲娇，但是又会认真解答的雌小鬼"

# 会话标识
if "current_session" not in st.session_state:
    # 获取系统时间
    st.session_state.current_session = generate_session_name()

# 模型选择（首次运行给默认值）
if 'model' not in st.session_state:
    st.session_state.model = "deepseek-v4-pro"

# temperature（首次运行给默认值）
if 'temperature' not in st.session_state:
    st.session_state.temperature = 1.0

# 聊天信息显示
for message in st.session_state.messages:
    st.chat_message(message["role"]).write(message["content"])

# 侧边栏
with st.sidebar:  # with streamlit中上下文管理器
    st.subheader("AI控制面板")

    # key 双向绑定：选中值自动写入 st.session_state.model
    st.selectbox("模型", MODEL_OPTIONS, key="model")
    st.slider("temperature（越高越有创意，越低越稳定）",
              min_value=0.0, max_value=2.0, step=0.1, key="temperature")

    # 点击后触发 on_new_session 回调
    st.button("新建会话", width="stretch", icon="✍️", on_click=on_new_session)

    # 会话历史（倒序，最新的排在上面）
    st.text("会话历史")
    for session in sorted(load_sessions(), reverse=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            # 当前正在进行的会话禁点加载
            st.button(session, width="stretch", icon="📖", key=f"load_{session}",
                      on_click=on_load_session, args=(session,),
                      disabled=(session == st.session_state.current_session))
        with col2:
            # 删除按钮改成唤起对话框
            if st.button(" ", icon="❌️", key=f"delete_{session}"):
                confirm_delete(session)

    st.subheader("伴侣信息")
    # 带 key 的组件会自动把输入值写入 session_state，无需手动赋值
    st.text_input("昵称", placeholder="Ta的名字是:", key="nick_name")
    st.text_area("性格（人设）", placeholder="Ta是......", key="identity")

# 聊天输入框
prompt = st.chat_input("请输入您的问题")
if prompt:  # 字符串自动转化为bool值
    # 校验：昵称和人设没填完不允许提问
    if not st.session_state.nick_name or not st.session_state.identity:
        st.warning("请先在侧边栏填写 Ta 的昵称和性格（人设）哦~")
        st.stop()

    st.chat_message("user").write(prompt)
    print("---------->,调用AI大模型，提示词:", prompt)
    # 添加用户提示词到聊天信息中
    st.session_state.messages.append({"role": "user", "content": prompt})

    # 调用AI大模型
    try:
      response = client.chat.completions.create(
        model=st.session_state.model,  # 改
        temperature=st.session_state.temperature,  # 新增
        messages=build_context(
              system_prompt % (st.session_state.nick_name, st.session_state.identity),  # 字符串
              st.session_state.messages,  # 整个列表，不加 *
              max_turns=40
        ),
        stream=True,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}}
      )
      response_message = st.empty()  # 创建一个空的组件

      full_response = ""
      for chunk in response:
         if not chunk.choices:  # 跳过空 chunk（如用量统计帧），防止 IndexError
            continue
         if chunk.choices[0].delta.content is not None:
            content = chunk.choices[0].delta.content
            full_response += content
            response_message.chat_message("assistant").write(full_response)

    except openai.AuthenticationError:
        st.error("API Key 无效，请检查 DEEPSEEK_API_KEY")
        st.session_state.messages.pop()
        st.stop()
    except Exception as e:
        st.error(f"出现了问题{e},请检查token余额或网络连接")
        st.session_state.messages.pop()
        st.stop()

    # # 大模型返回结果(流式)
    # response_message = st.empty()  # 创建一个空的组件
    #
    # full_response = ""
    # for chunk in response:
    #     if not chunk.choices:  # 跳过空 chunk（如用量统计帧），防止 IndexError
    #         continue
    #     if chunk.choices[0].delta.content is not None:
    #         content = chunk.choices[0].delta.content
    #         full_response += content
    #         response_message.chat_message("assistant").write(full_response)

    # 添加AI大模型返回结果到聊天信息中
    st.session_state.messages.append({"role": "assistant", "content": full_response})
    # 每轮对话结束后自动保存会话
    save_session()