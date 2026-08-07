import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

function App() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-8">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>ima 知识库</CardTitle>
          <CardDescription>智能知识库问答系统 (Web 版 ima)</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Button>shadcn Button 验证</Button>
          <Button variant="outline">Outline 按钮</Button>
          <Button variant="ghost">Ghost 按钮</Button>
        </CardContent>
      </Card>
    </div>
  )
}

export default App
