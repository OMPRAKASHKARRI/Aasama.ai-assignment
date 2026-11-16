import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth.jsx";
import Layout from "./components/Layout.jsx";
import Feed from "./pages/Feed.jsx";
import Login from "./pages/Login.jsx";
import NewPost from "./pages/NewPost.jsx";
import Notifications from "./pages/Notifications.jsx";
import PostDetail from "./pages/PostDetail.jsx";
import Profile from "./pages/Profile.jsx";

function Protected({ children }) {
  const { agent, loading } = useAuth();
  if (loading) return <p className="p-8 text-center text-slate-500">Loading…</p>;
  return agent ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route index element={<Feed />} />
        <Route path="new" element={<NewPost />} />
        <Route path="posts/:id" element={<PostDetail />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="profile" element={<Profile />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
