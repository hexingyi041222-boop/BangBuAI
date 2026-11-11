# BangBuAI AI 工程展示

这里展示 BangBuAI 中最能体现 AI 应用工程能力的一组核心实现。内容聚焦在对话工作流、模型与业务服务适配、工具路由、记忆及提示词设计；这是经过挑选的代码展示目录，不是完整应用仓库。

## 项目简介

BangBuAI 是一个面向桌面陪伴场景的 AI 对话后端原型。它将输入理解、工具判断、上下文组织、回复生成和语音/情绪处理组合成可扩展的工作流，并通过服务适配层隔离模型和外部业务能力。

## 目录内容

### graph/：对话工作流与节点

- graph.py：使用 LangGraph 组织完整对话图，并单独构建只执行 ASR 与情绪分析的分析图。
- state.py：定义节点之间传递的会话状态。
- nodes/：按职责拆分 ASR、工具路由、记忆召回/更新、回复生成、TTS、情绪分析和跟进节点。

主对话路径大致为：输入转写 → 会话跟进检查 → 工具路由；普通对话继续经过记忆召回和回复生成，之后生成语音、分析本轮情绪并更新后续记忆。工具已处理的分支可以跳过普通回复流程。独立情绪分析图则只执行 ASR 和情绪分析，避免触发对话、工具或 TTS 等副作用。

### services/：外部能力和会话能力适配

- doubao.py、asr.py：模型/语音能力的 Mock 与真实服务调用、超时和重试处理。
- backend_tools.py、backend_tools_http.py：业务工具协议及 HTTP 适配，包括参数校验、错误分类、超时和幂等键处理。
- tool_intents.py、permissions.py：工具意图解析与权限边界。
- memory.py、emotion_records.py、daily_message.py：记忆处理、情绪事件整理和每日留言逻辑。
- session.py、failure_counter.py：会话生命周期与失败计数。
- tts.py、devices.py、mqtt.py、risk.py：语音回执、设备状态、消息传输及风险相关辅助能力。

### prompts/：按任务拆分的提示词

- dialogue.py：普通对话及回复生成。
- speech.py：音频转写、情绪分析和 TTS 指令。
- daily_message.py：每日留言生成。

提示词与代码分开管理，便于按任务维护并跟踪版本变化。
