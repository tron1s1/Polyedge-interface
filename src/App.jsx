import { Routes, Route } from 'react-router-dom'
import { ThemeProvider } from './context/ThemeContext'
import { ModeProvider } from './context/ModeContext'
import TopNav from './components/layout/TopNav'
import DashboardPage from './pages/DashboardPage'
import NodesPage from './pages/NodesPage'
import StrategiesPage from './pages/StrategiesPage'
import StrategyDetailPage from './pages/StrategyDetailPage'
import PortfolioPage from './pages/PortfolioPage'
import RiskPage from './pages/RiskPage'
import TaxPage from './pages/TaxPage'
import ScannerPage from './pages/ScannerPage'
import AnalyticsPage from './pages/AnalyticsPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <ThemeProvider>
      <ModeProvider>
        <div className="min-h-screen bg-[var(--color-background)] text-[var(--color-foreground)]">
          <TopNav />
          <div className="pt-12">
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/nodes" element={<NodesPage />} />
              <Route path="/strategies" element={<StrategiesPage />} />
              <Route path="/strategies/:strategyId" element={<StrategyDetailPage />} />
              <Route path="/portfolio" element={<PortfolioPage />} />
              <Route path="/risk" element={<RiskPage />} />
              <Route path="/tax" element={<TaxPage />} />
              <Route path="/scanner" element={<ScannerPage />} />
              <Route path="/analytics" element={<AnalyticsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </div>
        </div>
      </ModeProvider>
    </ThemeProvider>
  )
}
