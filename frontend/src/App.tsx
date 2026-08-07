import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { Toaster } from "@/components/ui/sonner"
import { isLoggedIn } from "@/lib/auth"
import LoginPage from "@/pages/LoginPage"
import MainPage from "@/pages/MainPage"
import RegisterPage from "@/pages/RegisterPage"

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!isLoggedIn()) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <MainPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster />
    </BrowserRouter>
  )
}

export default App
