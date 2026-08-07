function ChatArea() {
  return (
    <div className="flex h-full flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
      <p className="text-sm">选择左侧知识库开始提问</p>
      <p className="text-xs">问答管线将在批次 5 接入（流式输出 + 引用溯源）</p>
    </div>
  )
}

export default ChatArea
