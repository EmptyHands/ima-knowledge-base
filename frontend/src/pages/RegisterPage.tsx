import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ApiError, api } from "@/lib/api"
import { setToken } from "@/lib/auth"

function RegisterPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    if (password.length < 6) {
      setError("密码至少 6 位")
      return
    }
    if (password !== confirm) {
      setError("两次输入的密码不一致")
      return
    }
    setLoading(true)
    try {
      await api.post("/api/v1/auth/register", { username, password })
      const res = await api.post<{ access_token: string }>("/api/v1/auth/login", {
        username,
        password,
      })
      setToken(res.access_token)
      navigate("/")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "注册失败，请稍后重试")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">注册账号</CardTitle>
          <CardDescription>创建你的 ima 知识库账号</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <Input
              type="text"
              placeholder="用户名（至少 3 位）"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
            <Input
              type="password"
              placeholder="密码（至少 6 位）"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <Input
              type="password"
              placeholder="确认密码"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? "注册中…" : "注册并登录"}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              已有账号？{" "}
              <Link to="/login" className="text-primary hover:underline">
                去登录
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

export default RegisterPage
