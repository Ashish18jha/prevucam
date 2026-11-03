import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { LiveProvider } from "./context/LiveContext";
import { WebcamProvider } from "./context/WebcamContext";
import CameraSettings from "./pages/CameraSettings";
import Dashboard from "./pages/Dashboard";
import DetectionSettings from "./pages/DetectionSettings";
import EventDetails from "./pages/EventDetails";
import Events from "./pages/Events";
import LiveMonitoring from "./pages/LiveMonitoring";
import Notifications from "./pages/Notifications";
import Reports from "./pages/Reports";
import SystemSettings from "./pages/SystemSettings";
import Timelapse from "./pages/Timelapse";
import AnalysisDetail from "./pages/AnalysisDetail";
import VideoAnalysis from "./pages/VideoAnalysis";
import Zones from "./pages/Zones";

export default function App() {
  return (
    <LiveProvider>
      <WebcamProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="live" element={<LiveMonitoring />} />
            <Route path="events" element={<Events />} />
            <Route path="events/:id" element={<EventDetails />} />
            <Route path="video-analysis" element={<VideoAnalysis />} />
            <Route path="video-analysis/:id" element={<AnalysisDetail />} />
            <Route path="zones" element={<Zones />} />
            <Route path="detection" element={<DetectionSettings />} />
            <Route path="camera" element={<CameraSettings />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="reports" element={<Reports />} />
            <Route path="timelapse" element={<Timelapse />} />
            <Route path="system" element={<SystemSettings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </WebcamProvider>
    </LiveProvider>
  );
}
