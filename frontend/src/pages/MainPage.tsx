import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { ApiError, api } from "@/lib/api"
import { clearToken } from "@/lib/auth"

function MainPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState("")

  useEffect(() => {
    api
      .get<{ username: string }>("/api/v1/auth/me")
      .then((res) => setUsername(res.username))
      .catch(() => {})
  }, [])

  function handleLogout() {
    clearToken()
    navigate("/login")
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-semibold">主界面（Task 12 实现）</h1>
      {username && <p className="text-muted-foreground">当前用户：{username}</p>}
      <Button variant="outline" onClick={handleLogout}>
        退出登录
      </Button>
    </div>
  )
}

export default MainPage
