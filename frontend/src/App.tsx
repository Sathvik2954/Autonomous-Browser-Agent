import React, { useState, useEffect, useRef } from 'react';
import {
  Home,
  Bot,
  Globe,
  BarChart2,
  FolderOpen,
  Settings,
  Sun,
  Moon,
  Search,
  Plus,
  Bell,
  User,
  Play,
  RotateCcw,
  CheckCircle2,
  Clock,
  Terminal,
  Download,
  AlertOctagon,
  RefreshCw,
  ArrowLeft,
  ArrowRight,
  Sparkles,
  Search as SearchIcon,
  BookOpen,
  Calendar
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// Types
interface TaskAction {
  id: number;
  step: number;
  action_type: string;
  description: string;
  screenshot_path?: string;
  url?: string;
  timestamp: string;
}

interface LogEntry {
  id: number;
  message: string;
  level: string;
  timestamp: string;
}

interface TaskRecord {
  id: string;
  prompt: string;
  status: string;
  started_at: string;
  completed_at?: string;
  error?: string;
  result_summary?: string;
}

interface DOMElement {
  id: string;
  type: string;
  tagName: string;
  text: string;
  placeholder?: string;
  href?: string;
  checked: boolean;
  disabled: boolean;
  selector: string;
}

export default function App() {
  // Navigation & Theme
  const [activeTab, setActiveTab] = useState<'dashboard' | 'tasks' | 'browser' | 'reports' | 'history' | 'settings'>('dashboard');
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('theme');
    return (saved as 'light' | 'dark') || 'light';
  });

  // Task & Polling States
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<TaskRecord | null>(null);
  const [actions, setActions] = useState<TaskAction[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [extractedData, setExtractedData] = useState<any[]>([]);
  const [elements, setElements] = useState<DOMElement[]>([]);
  const [videoExists, setVideoExists] = useState(false);
  const [latestScreenshotUrl, setLatestScreenshotUrl] = useState<string | null>(null);
  const [inspectedStep, setInspectedStep] = useState<number | null>(null);
  const [reportContent, setReportContent] = useState('Final markdown report will appear here once the task completes successfully.');
  
  // Settings Form States
  const [provider, setProvider] = useState('mistral');
  const [geminiKey, setGeminiKey] = useState('');
  const [groqKey, setGroqKey] = useState('');
  const [mistralKey, setMistralKey] = useState('');
  const [headless, setHeadless] = useState(false);

  // General UI States
  const [promptValue, setPromptValue] = useState('');
  const [taskHistory, setTaskHistory] = useState<TaskRecord[]>([]);
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const [toasts, setToasts] = useState<{ id: string; message: string; type: 'success' | 'info' | 'error' }[]>([]);
  
  const terminalEndRef = useRef<HTMLDivElement>(null);

  // Initialize theme
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  // Load Task History on mount
  useEffect(() => {
    fetchTaskHistory();
  }, []);

  // Poll active task when running
  useEffect(() => {
    let intervalId: any = null;
    if (activeTaskId) {
      intervalId = setInterval(pollActiveTaskDetails, 1500);
      pollActiveTaskDetails(); // Immediate first poll
    } else {
      if (intervalId) clearInterval(intervalId);
    }
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [activeTaskId]);

  // Scroll terminal logs
  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  // Listen for Cmd/Ctrl + K Command Palette shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setShowCommandPalette(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const showToast = (message: string, type: 'success' | 'info' | 'error' = 'info') => {
    const id = Math.random().toString(36).substring(7);
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4000);
  };

  const fetchTaskHistory = async () => {
    try {
      const response = await fetch('/api/tasks');
      if (response.ok) {
        const data = await response.json();
        setTaskHistory(data);
      }
    } catch (e) {
      console.error("Error fetching history:", e);
    }
  };

  const startTask = async (promptText: string) => {
    if (!promptText.trim()) return;
    try {
      showToast("Launching browser agent task...", "info");
      const response = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: promptText,
          provider: provider,
          headless: headless
        })
      });
      if (response.ok) {
        const data = await response.json();
        setActiveTaskId(data.task_id);
        setInspectedStep(null);
        setActiveTab('tasks');
        showToast("Task successfully scheduled!", "success");
        fetchTaskHistory();
      } else {
        const err = await response.text();
        showToast(`Failed to launch: ${err}`, "error");
      }
    } catch (e) {
      showToast("Connection to backend failed", "error");
    }
  };

  const stopTask = async (id: string) => {
    try {
      const response = await fetch(`/api/tasks/${id}/stop`, { method: 'POST' });
      if (response.ok) {
        showToast("Task stop requested", "info");
      }
    } catch (e) {
      console.error(e);
    }
  };

  const pollActiveTaskDetails = async () => {
    if (!activeTaskId) return;
    try {
      const response = await fetch(`/api/tasks/${activeTaskId}`);
      if (response.ok) {
        const data = await response.json();
        setActiveTask(data.task);
        setActions(data.actions);
        setLogs(data.logs);
        setExtractedData(data.extracted_data);
        setElements(data.elements || []);
        setVideoExists(data.video_exists);
        if (data.latest_screenshot) {
          setLatestScreenshotUrl(data.latest_screenshot);
        }
        
        // Stop polling if task is finalized
        if (data.task.status === 'completed' || data.task.status === 'failed' || data.task.status === 'stopped') {
          showToast(`Task finished with status: ${data.task.status}`, data.task.status === 'completed' ? 'success' : 'error');
          setActiveTaskId(null);
          fetchTaskHistory();
          loadReportMarkdown(activeTaskId);
        }
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  };

  const selectTaskFromHistory = (id: string) => {
    setActiveTaskId(id);
    setInspectedStep(null);
    pollActiveTaskDetails();
    loadReportMarkdown(id);
    setActiveTab('tasks');
  };

  const getActiveStepDetails = () => {
    if (inspectedStep !== null) {
      return actions.find(a => a.step === inspectedStep) || null;
    }
    return actions[actions.length - 1] || null;
  };

  const handleApplySettings = async (e: React.FormEvent) => {
    e.preventDefault();
    showToast("Application settings updated successfully", "success");
  };

  const loadReportMarkdown = async (taskId: string) => {
    try {
      const res = await fetch(`/api/tasks/${taskId}/report`);
      if (res.ok) {
        const data = await res.json();
        setReportContent(data.content);
      } else {
        setReportContent("Report details are not generated yet.");
      }
    } catch (err: any) {
      setReportContent(`Error loading report: ${err.message}`);
    }
  };

  const exportData = (format: string) => {
    if (!activeTaskId) return;
    window.open(`/api/tasks/${activeTaskId}/export/${format}`);
  };

  return (
    <div className="flex h-screen overflow-hidden bg-[#F8FAFC] dark:bg-[#09090B] text-[#0F172A] dark:text-[#FAFAFA]">
      
      {/* Toast Notification Container */}
      <div className="fixed top-6 right-6 z-[100] flex flex-col gap-3">
        <AnimatePresence>
          {toasts.map(t => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: -20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl border backdrop-blur-md shadow-lg min-w-[280px] max-w-[400px]
                ${t.type === 'success' ? 'bg-[#22C55E]/10 border-[#22C55E]/30 text-[#22C55E]' : ''}
                ${t.type === 'error' ? 'bg-[#EF4444]/10 border-[#EF4444]/30 text-[#EF4444]' : ''}
                ${t.type === 'info' ? 'bg-[#2563EB]/10 border-[#2563EB]/30 text-[#2563EB]' : ''}
              `}
            >
              {t.type === 'success' && <CheckCircle2 className="w-5 h-5 shrink-0" />}
              {t.type === 'error' && <AlertOctagon className="w-5 h-5 shrink-0" />}
              {t.type === 'info' && <Bot className="w-5 h-5 shrink-0" />}
              <span className="text-sm font-medium">{t.message}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* 1. Left Sidebar */}
      <aside className="w-[280px] shrink-0 border-r border-slate-200/50 dark:border-zinc-800/50 bg-white dark:bg-[#18181B] flex flex-col justify-between p-5">
        <div className="flex flex-col gap-8">
          {/* Logo Section */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#2563EB] to-[#6366F1] dark:from-[#60A5FA] dark:to-[#818CF8] shadow-md shadow-[#2563EB]/20 dark:shadow-[#60A5FA]/10 flex items-center justify-center font-bold text-white">
              B
            </div>
            <div>
              <h1 className="font-bold text-sm tracking-wide bg-gradient-to-r from-[#0F172A] to-[#6366F1] dark:from-[#FAFAFA] to-[#818CF8] bg-clip-text text-transparent">
                Browser Agent
              </h1>
              <p className="text-[10px] text-slate-500 dark:text-zinc-400 font-medium uppercase tracking-wider">
                Automation Suite
              </p>
            </div>
          </div>

          {/* Navigation Section */}
          <nav className="flex flex-col gap-1.5">
            {[
              { id: 'dashboard', label: 'Dashboard', icon: Home },
              { id: 'tasks', label: 'Tasks', icon: Bot },
              { id: 'browser', label: 'Developer Console', icon: Globe },
              { id: 'reports', label: 'Reports', icon: BarChart2 },
              { id: 'history', label: 'History', icon: FolderOpen },
              { id: 'settings', label: 'Settings', icon: Settings },
            ].map(item => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id as any)}
                  className={`flex items-center gap-3.5 px-4 py-3 rounded-xl text-sm font-semibold transition-all duration-200 ${
                    isActive
                      ? 'bg-[#2563EB]/10 dark:bg-[#60A5FA]/10 text-[#2563EB] dark:text-[#60A5FA] shadow-sm'
                      : 'text-slate-500 dark:text-zinc-400 hover:bg-slate-100/50 dark:hover:bg-zinc-800/40 hover:text-[#0F172A] dark:hover:text-[#FAFAFA]'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Sidebar Bottom */}
        <div className="flex flex-col gap-4 border-t border-slate-200/50 dark:border-zinc-800/50 pt-5">
          {/* Connection Status */}
          <div className="flex items-center justify-between px-2 text-xs">
            <span className="text-slate-500 dark:text-zinc-400 font-medium">Status</span>
            <div className="flex items-center gap-1.5 font-semibold text-[#22C55E]">
              <span className="w-2 h-2 rounded-full bg-[#22C55E] animate-pulse"></span>
              Online
            </div>
          </div>

          {/* Profile Card */}
          <div className="flex items-center gap-3 p-2 bg-slate-50 dark:bg-zinc-800/20 border border-slate-100 dark:border-zinc-800/40 rounded-xl">
            <div className="w-8 h-8 rounded-lg bg-[#6366F1]/20 dark:bg-[#818CF8]/20 flex items-center justify-center text-[#6366F1] dark:text-[#818CF8] font-semibold text-xs">
              JD
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold truncate">Local Operator</p>
              <p className="text-[10px] text-slate-500 dark:text-zinc-400 truncate font-mono">operator@agent.local</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Pane */}
      <div className="flex-1 flex flex-col overflow-hidden relative">
        
        {/* 2. Sticky Top Navigation Bar */}
        <header className="h-[70px] shrink-0 border-b border-slate-200/50 dark:border-zinc-800/50 bg-white/70 dark:bg-[#09090B]/70 backdrop-blur-md flex items-center justify-between px-6 z-20">
          <div className="flex items-center gap-4">
            <h2 className="font-bold text-lg capitalize tracking-tight">{activeTab}</h2>
            {activeTask && activeTab !== 'dashboard' && (
              <div className="flex items-center gap-2 px-3 py-1 bg-[#2563EB]/5 dark:bg-[#60A5FA]/5 border border-[#2563EB]/10 dark:border-[#60A5FA]/10 rounded-lg text-xs font-medium text-[#2563EB] dark:text-[#60A5FA]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#2563EB] dark:bg-[#60A5FA] animate-pulse"></span>
                Active: {activeTask.id}
              </div>
            )}
          </div>

          <div className="flex items-center gap-4">
            {/* Command palette input */}
            <button
              onClick={() => setShowCommandPalette(true)}
              className="flex items-center gap-2 px-3 py-2 bg-slate-100/50 dark:bg-zinc-800/30 hover:bg-slate-100 dark:hover:bg-zinc-800/50 border border-slate-200/50 dark:border-zinc-800/50 rounded-xl text-xs text-slate-500 dark:text-zinc-400 transition-all w-60"
            >
              <Search className="w-3.5 h-3.5" />
              <span className="flex-1 text-left">Search or run command...</span>
              <kbd className="px-1.5 py-0.5 bg-slate-200 dark:bg-zinc-700 rounded text-[9px] font-bold">Ctrl K</kbd>
            </button>

            {/* Theme Toggle */}
            <button
              onClick={() => setTheme(prev => prev === 'light' ? 'dark' : 'light')}
              className="w-9 h-9 border border-slate-200/50 dark:border-zinc-800/50 bg-slate-50/50 dark:bg-zinc-800/10 hover:bg-slate-100 dark:hover:bg-zinc-800/50 rounded-xl flex items-center justify-center transition-all"
            >
              {theme === 'light' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
            </button>

            {/* Profile Avatar */}
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-[#6366F1] to-[#d946ef] p-0.5">
              <div className="w-full h-full rounded-[10px] bg-white dark:bg-[#09090B] flex items-center justify-center">
                <User className="w-4 h-4" />
              </div>
            </div>
          </div>
        </header>

        {/* Inner Horizontal Flex Container for Workspace and Sidebar Logs */}
        <div className="flex-1 flex overflow-hidden relative">
          
          {/* 3. Main Workspace Container */}
          <main className="flex-1 overflow-y-auto p-5 bg-slate-50/50 dark:bg-zinc-950/20">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -15 }}
                transition={{ duration: 0.2 }}
                className="h-full"
              >
                
                {/* DASHBOARD PAGE */}
                {activeTab === 'dashboard' && (
                  <div className="max-w-4xl mx-auto flex flex-col gap-6 py-2">
                    {/* Hero Header */}
                    <div className="text-center flex flex-col gap-3">
                      <h3 className="text-3xl font-extrabold tracking-tight">What would you like the Browser Agent to do?</h3>
                      <p className="text-sm text-slate-500 dark:text-zinc-400">
                        Type your instruction in plain language. The agent will spin up a headless browser to complete it.
                      </p>
                    </div>

                    {/* AI Prompt Box */}
                    <div className="p-2 bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl shadow-xl flex flex-col gap-2 relative">
                      <textarea
                        value={promptValue}
                        onChange={e => setPromptValue(e.target.value)}
                        placeholder="e.g., Search cheapest iPhone 15 under Rs 65000 on Google and report prices"
                        className="w-full h-32 bg-transparent text-sm p-4 outline-none resize-none font-medium placeholder-slate-400"
                      />
                      <div className="flex justify-between items-center px-4 py-2 border-t border-slate-100 dark:border-zinc-800/40">
                        <span className="text-[10px] text-slate-500 dark:text-zinc-400 flex items-center gap-1">
                          <Sparkles className="w-3.5 h-3.5 text-[#6366F1]" />
                          Autonomous Automation Mode
                        </span>
                        <button
                          onClick={() => startTask(promptValue)}
                          disabled={!promptValue.trim()}
                          className="flex items-center gap-2 bg-gradient-to-r from-[#2563EB] to-[#6366F1] text-white px-5 py-2.5 rounded-xl text-xs font-bold shadow-md hover:shadow-lg transition-all duration-200 disabled:opacity-50 disabled:pointer-events-none"
                        >
                          <Play className="w-3.5 h-3.5 fill-current" />
                          Execute Prompt
                        </button>
                      </div>
                    </div>

                    {/* Suggested Prompts Cards Grid */}
                    <div className="flex flex-col gap-4">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-zinc-400">Suggested Prompt Templates</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {[
                          { title: "Amazon search prices", desc: "Find the cheapest laptop under 60000 rupees on Amazon.", icon: SearchIcon },
                          { title: "Wikipedia summary", desc: "Open Wikipedia, look up Quantum Computing, and summarize.", icon: BookOpen },
                          { title: "Form filling demo", desc: "Open mock form page and submit appointment inputs.", icon: Calendar },
                        ].map((item, idx) => {
                          const Icon = item.icon;
                          return (
                            <div
                              key={idx}
                              onClick={() => setPromptValue(item.desc)}
                              className="p-5 bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-xl cursor-pointer hover:border-[#2563EB] dark:hover:border-[#60A5FA] hover:shadow-md transition-all duration-200 flex flex-col gap-3 group"
                            >
                              <div className="w-8 h-8 rounded-lg bg-[#2563EB]/5 dark:bg-[#60A5FA]/5 flex items-center justify-center text-[#2563EB] dark:text-[#60A5FA] group-hover:bg-[#2563EB]/10 transition-colors">
                                <Icon className="w-4 h-4" />
                              </div>
                              <div>
                                <h5 className="font-bold text-xs capitalize">{item.title}</h5>
                                <p className="text-[11px] text-slate-500 dark:text-zinc-400 mt-1 leading-relaxed">{item.desc}</p>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}

                {/* TASKS EXECUTION PAGE */}
                {activeTab === 'tasks' && (
                  <div className="h-full flex gap-4 overflow-hidden">
                    {/* Left Column: Viewport & Terminal stacked vertically */}
                    <div className="flex-1 flex flex-col gap-4 h-full overflow-hidden">
                      {/* Browser Viewport Frame */}
                      <div className="flex-1 flex flex-col bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl overflow-hidden shadow-lg">
                        {/* Browser Mockup Header */}
                        <div className="px-4 py-3 bg-slate-50 dark:bg-zinc-900 border-b border-slate-100 dark:border-zinc-800/50 flex items-center gap-3">
                          <div className="flex gap-1.5 shrink-0">
                            <span className="w-2.5 h-2.5 rounded-full bg-[#EF4444]"></span>
                            <span className="w-2.5 h-2.5 rounded-full bg-[#F59E0B]"></span>
                            <span className="w-2.5 h-2.5 rounded-full bg-[#22C55E]"></span>
                          </div>
                          <div className="flex gap-1 border-r border-slate-200 dark:border-zinc-800 pr-2 shrink-0">
                            <button className="p-1 hover:bg-slate-200 dark:hover:bg-zinc-800 rounded transition-colors"><ArrowLeft className="w-3.5 h-3.5" /></button>
                            <button className="p-1 hover:bg-slate-200 dark:hover:bg-zinc-800 rounded transition-colors"><ArrowRight className="w-3.5 h-3.5" /></button>
                            <button className="p-1 hover:bg-slate-200 dark:hover:bg-zinc-800 rounded transition-colors"><RefreshCw className="w-3.5 h-3.5" /></button>
                          </div>
                          <div className="flex-1 bg-slate-100 dark:bg-zinc-950 border border-slate-200/50 dark:border-zinc-800/40 rounded-lg px-3 py-1.5 text-xs text-slate-500 dark:text-zinc-400 font-medium overflow-hidden text-overflow-ellipsis whitespace-nowrap">
                            {getActiveStepDetails()?.url || "about:blank"}
                          </div>
                        </div>

                        {/* Viewport Frame */}
                        <div className="flex-1 bg-slate-900 flex items-center justify-center overflow-hidden relative">
                          {latestScreenshotUrl ? (
                            <img
                              src={`${latestScreenshotUrl}&cb=${Date.now()}`}
                              alt="Viewport"
                              className="max-w-full max-h-full object-contain"
                            />
                          ) : (
                            <div className="text-center text-slate-500 flex flex-col items-center gap-4">
                              <Globe className="w-12 h-12 stroke-[1.5] text-slate-600 animate-pulse" />
                              <div>
                                <h5 className="font-bold text-sm text-slate-400">Viewport Standby</h5>
                                <p className="text-xs text-slate-500 mt-1">Start a task to stream live page execution.</p>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Terminal Console (Sits underneath viewport!) */}
                      <div className="h-[240px] shrink-0 border border-slate-200/50 dark:border-zinc-800/50 bg-[#07090e] text-slate-100 flex flex-col rounded-2xl overflow-hidden shadow-xl">
                        <div className="px-5 py-3 border-b border-zinc-800 bg-zinc-900/60 flex items-center gap-2">
                          <Terminal className="w-4 h-4 text-[#818CF8]" />
                          <span className="font-mono text-xs uppercase font-bold tracking-wider">Agent Thinking Terminal Logs</span>
                        </div>
                        
                        <div className="flex-1 p-5 overflow-y-auto font-mono text-[11px] leading-relaxed flex flex-col gap-2.5">
                          {logs.length === 0 ? (
                            <div className="text-zinc-600">Standing by... logs will appear as agent thinks.</div>
                          ) : (
                            logs.map((log) => {
                              const time = new Date(log.timestamp).toLocaleTimeString([], { hour12: false });
                              return (
                                <div key={log.id} className="log-row">
                                  <span className="text-indigo-400 mr-2">[{time}]</span>
                                  <span className={`font-bold mr-2 uppercase ${
                                    log.level === 'thought' ? 'text-cyan-400' :
                                    log.level === 'error' ? 'text-rose-500' :
                                    log.level === 'warning' ? 'text-amber-400' : 'text-emerald-400'
                                  }`}>
                                    {log.level}
                                  </span>
                                  <span className={log.level === 'thought' ? 'text-cyan-200 italic' : 'text-zinc-300'}>
                                    {log.message}
                                  </span>
                                </div>
                              );
                            })
                          )}
                          <div ref={terminalEndRef}></div>
                        </div>
                      </div>
                    </div>

                    {/* Right Column: Execution Status, Findings, Action Timeline */}
                    <div className="w-[340px] shrink-0 flex flex-col gap-4 h-full overflow-y-auto pr-1">
                      {/* Execution Status Card */}
                      {activeTask && (
                        <div className="p-4 bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl shadow-sm flex flex-col gap-2.5">
                          <div className="flex justify-between items-center">
                            <span className="text-xs text-slate-500 dark:text-zinc-400 font-bold uppercase tracking-wider">Run Status</span>
                            <span className={`status-pill ${activeTask.status}`}>{activeTask.status}</span>
                          </div>
                          <p className="text-xs font-semibold leading-relaxed border-t border-slate-100 dark:border-zinc-800/50 pt-2.5">
                            {activeTask.prompt}
                          </p>
                        </div>
                      )}

                      {/* Final Result / Error Summary Card */}
                      {activeTask && activeTask.result_summary && (
                        <div className="p-4 bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800/40 rounded-2xl shadow-sm flex flex-col gap-2.5">
                          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                            <CheckCircle2 className="w-4 h-4" />
                            Agent Executive Findings
                          </div>
                          <p className="text-[11px] font-semibold text-slate-700 dark:text-zinc-300 leading-relaxed whitespace-pre-wrap max-h-[250px] overflow-y-auto">
                            {activeTask.result_summary}
                          </p>
                        </div>
                      )}

                      {activeTask && activeTask.error && (
                        <div className="p-4 bg-rose-50 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-800/40 rounded-2xl shadow-sm flex flex-col gap-2.5">
                          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-rose-600 dark:text-rose-400">
                            <AlertOctagon className="w-4 h-4" />
                            Execution Failure
                          </div>
                          <p className="text-[11px] font-semibold text-slate-700 dark:text-zinc-300 leading-relaxed">
                            {activeTask.error}
                          </p>
                        </div>
                      )}

                      {/* Action Timeline */}
                      <div className="flex flex-col bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl overflow-hidden shadow-sm shrink-0">
                        <div className="px-4 py-3 border-b border-slate-100 dark:border-zinc-800/50 bg-slate-50/50 dark:bg-zinc-900/30 flex justify-between items-center">
                          <span className="font-bold text-xs uppercase tracking-wider text-slate-500 dark:text-zinc-400">Action Steps Timeline</span>
                          {inspectedStep !== null && (
                            <button
                              onClick={() => setInspectedStep(null)}
                              className="text-[10px] font-bold text-[#2563EB] dark:text-[#60A5FA]"
                            >
                              Reset to Live
                            </button>
                          )}
                        </div>
                        
                        <div className="p-4 flex flex-col gap-3 max-h-[300px] overflow-y-auto">
                          {actions.length === 0 ? (
                            <div className="text-center py-10 text-slate-500 dark:text-zinc-400 text-xs">
                              No actions logged yet.
                            </div>
                          ) : (
                            actions.map((act) => (
                              <div
                                key={act.id}
                                onClick={() => setInspectedStep(act.step)}
                                className={`p-3.5 border rounded-xl cursor-pointer transition-all duration-200 flex gap-3.5 ${
                                  (inspectedStep === act.step || (inspectedStep === null && act.step === actions.length))
                                    ? 'bg-[#2563EB]/5 border-[#2563EB]/30 dark:bg-[#60A5FA]/5 dark:border-[#60A5FA]/30'
                                    : 'border-slate-200/50 dark:border-zinc-800/50 hover:bg-slate-50 dark:hover:bg-zinc-800/20'
                                }`}
                              >
                                <div className="w-5 h-5 rounded-full bg-[#2563EB]/10 text-[#2563EB] dark:text-[#60A5FA] text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5">
                                  {act.step}
                                </div>
                                <div>
                                  <h6 className="font-bold text-xs uppercase text-[#2563EB] dark:text-[#60A5FA]">{act.action_type}</h6>
                                  <p className="text-[11px] text-slate-500 dark:text-zinc-400 mt-1 leading-relaxed">{act.description}</p>
                                </div>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* BROWSER PAGE (DEVELOPER PANEL) */}
                {activeTab === 'browser' && (
                  <div className="h-full flex gap-6">
                    {/* Left Side: Real Live Browser Viewport Preview Frame */}
                    <div className="flex-1 flex flex-col bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl overflow-hidden shadow-lg">
                      {/* Browser Mockup Header */}
                      <div className="px-4 py-3 bg-slate-50 dark:bg-zinc-900 border-b border-slate-100 dark:border-zinc-800/50 flex items-center gap-3">
                        <div className="flex gap-1.5 shrink-0">
                          <span className="w-2.5 h-2.5 rounded-full bg-[#EF4444]"></span>
                          <span className="w-2.5 h-2.5 rounded-full bg-[#F59E0B]"></span>
                          <span className="w-2.5 h-2.5 rounded-full bg-[#22C55E]"></span>
                        </div>
                        <div className="flex gap-1 border-r border-slate-200 dark:border-zinc-800 pr-2 shrink-0">
                          <button className="p-1 hover:bg-slate-200 dark:hover:bg-zinc-800 rounded transition-colors"><ArrowLeft className="w-3.5 h-3.5" /></button>
                          <button className="p-1 hover:bg-slate-200 dark:hover:bg-zinc-800 rounded transition-colors"><ArrowRight className="w-3.5 h-3.5" /></button>
                          <button className="p-1 hover:bg-slate-200 dark:hover:bg-zinc-800 rounded transition-colors"><RefreshCw className="w-3.5 h-3.5" /></button>
                        </div>
                        <div className="flex-1 bg-slate-100 dark:bg-zinc-950 border border-slate-200/50 dark:border-zinc-800/40 rounded-lg px-3 py-1.5 text-xs text-slate-500 dark:text-zinc-400 font-medium overflow-hidden text-overflow-ellipsis whitespace-nowrap">
                          {getActiveStepDetails()?.url || "about:blank"}
                        </div>
                      </div>

                      {/* Viewport Frame */}
                      <div className="flex-1 bg-slate-900 flex items-center justify-center overflow-hidden relative min-h-[400px]">
                        {latestScreenshotUrl ? (
                          <img
                            src={`${latestScreenshotUrl}&cb=${Date.now()}`}
                            alt="Viewport"
                            className="max-w-full max-h-full object-contain"
                          />
                        ) : (
                          <div className="text-center text-slate-500 flex flex-col items-center gap-4">
                            <Globe className="w-12 h-12 stroke-[1.5] text-slate-600 animate-pulse" />
                            <div>
                              <h5 className="font-bold text-sm text-slate-400">Viewport Standby</h5>
                              <p className="text-xs text-slate-500 mt-1">Start a task to stream live page execution.</p>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Right Side: DOM Elements Inspector (actual dynamic elements!) */}
                    <div className="w-[380px] shrink-0 flex flex-col bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl overflow-hidden shadow-sm">
                      <div className="px-5 py-4 border-b border-slate-100 dark:border-zinc-800/50 bg-slate-50/50 dark:bg-zinc-900/30 flex justify-between items-center">
                        <span className="font-bold text-xs uppercase tracking-wider text-slate-500 dark:text-zinc-400">Interactive DOM Tree</span>
                        <span className="text-[10px] text-[#2563EB] dark:text-[#60A5FA] font-bold">{elements.length} Tagged</span>
                      </div>
                      
                      <div className="flex-1 overflow-y-auto p-5 font-mono text-[11px] leading-relaxed flex flex-col gap-3">
                        {elements.length === 0 ? (
                          <div className="text-center text-slate-400 py-10 font-sans text-xs">
                            DOM Tree Standby. Start a task to analyze active webpage interactive components.
                          </div>
                        ) : (
                          elements.map((el) => (
                            <div key={el.id} className="p-2 border border-slate-100 dark:border-zinc-800/40 rounded-lg hover:border-light-primary dark:hover:border-dark-primary transition-all">
                              <div className="flex justify-between text-[9px] font-bold text-slate-400 mb-1">
                                <span>{el.tagName}</span>
                                <span className="text-indigo-400">id: {el.id}</span>
                              </div>
                              <div className="text-[#0F172A] dark:text-indigo-300 font-semibold break-all">
                                {el.tagName.toLowerCase() === 'input' ? (
                                  `[input-id="${el.id}"] placeholder="${el.placeholder || ''}"`
                                ) : (
                                  `[button-id="${el.id}"] text="${el.text || ''}"`
                                )}
                              </div>
                              {el.href && (
                                <div className="text-[10px] text-slate-400 mt-1 truncate">href: {el.href}</div>
                              )}
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* REPORTS PAGE */}
                {activeTab === 'reports' && (
                  <div className="max-w-4xl mx-auto flex flex-col gap-6">
                    {/* Download Exporter Card */}
                    <div className="p-6 bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl shadow-sm flex flex-col md:flex-row justify-between items-center gap-4">
                      <div>
                        <h5 className="font-bold text-sm">Download Run Reports</h5>
                        <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">Export extracted datasets and logs compiled directly from the browser agent SQLite storage.</p>
                      </div>
                      <div className="flex gap-3 shrink-0">
                        <button
                          onClick={() => showToast("Exporting data as CSV...", "info")}
                          className="flex items-center gap-2 border border-slate-200 dark:border-zinc-800 hover:border-[#2563EB] dark:hover:border-[#60A5FA] px-4 py-2 rounded-xl text-xs font-semibold bg-white dark:bg-[#18181B] transition-all"
                        >
                          <Download className="w-3.5 h-3.5 text-[#2563EB]" />
                          Download CSV
                        </button>
                        <button
                          onClick={() => showToast("Exporting data as JSON...", "info")}
                          className="flex items-center gap-2 border border-slate-200 dark:border-zinc-800 hover:border-[#2563EB] dark:hover:border-[#60A5FA] px-4 py-2 rounded-xl text-xs font-semibold bg-white dark:bg-[#18181B] transition-all"
                        >
                          <Download className="w-3.5 h-3.5 text-[#2563EB]" />
                          Download JSON
                        </button>
                      </div>
                    </div>

                    {/* Render Extracted Data Tab Grid */}
                    <div className="bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl overflow-hidden shadow-sm flex flex-col">
                      <div className="px-5 py-4 border-b border-slate-100 dark:border-zinc-800/50 bg-slate-50/50 dark:bg-zinc-900/30 flex justify-between items-center">
                        <span className="font-bold text-xs uppercase tracking-wider text-slate-500 dark:text-zinc-400">Collected Dataset Data</span>
                        <span className="text-[10px] text-[#2563EB] dark:text-[#60A5FA] font-bold">{extractedData.length} records found</span>
                      </div>
                      
                      <div className="overflow-x-auto">
                        <table className="w-full text-left border-collapse text-xs">
                          <thead>
                            <tr className="bg-slate-50 dark:bg-zinc-900/40 border-b border-slate-100 dark:border-zinc-800/50">
                              <th className="p-4 font-bold text-slate-500 dark:text-zinc-400">Index</th>
                              <th className="p-4 font-bold text-slate-500 dark:text-zinc-400">Data Details</th>
                            </tr>
                          </thead>
                          <tbody>
                            {extractedData.length === 0 ? (
                              <tr>
                                <td colSpan={2} className="p-8 text-center text-slate-500 dark:text-zinc-400">
                                  No structured datasets collected. Execute a scraping or price comparison prompt to gather data.
                                </td>
                              </tr>
                            ) : (
                              extractedData.map((item, idx) => (
                                <tr key={idx} className="border-b border-slate-100 dark:border-zinc-800/50 last:border-0 hover:bg-slate-50/50 dark:hover:bg-zinc-800/10">
                                  <td className="p-4 font-bold">{idx + 1}</td>
                                  <td className="p-4 font-mono text-[11px]">{JSON.stringify(item)}</td>
                                </tr>
                              ))
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {/* Executive Findings Report */}
                    <div className="p-6 bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl shadow-sm flex flex-col gap-3">
                      <h5 className="font-bold text-xs uppercase tracking-wider text-slate-500 dark:text-zinc-400">Executive Task Report</h5>
                      <div className="text-xs leading-relaxed whitespace-pre-wrap font-sans p-4 bg-slate-50 dark:bg-zinc-900/30 border border-slate-100 dark:border-zinc-800/20 rounded-xl max-h-[400px] overflow-y-auto">
                        {reportContent}
                      </div>
                    </div>
                  </div>
                )}

                {/* HISTORY TIMELINE PAGE */}
                {activeTab === 'history' && (
                  <div className="max-w-4xl mx-auto flex flex-col gap-4">
                    {taskHistory.length === 0 ? (
                      <div className="text-center py-20 bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl">
                        <FolderOpen className="w-12 h-12 text-slate-500 dark:text-zinc-400 mx-auto stroke-[1.5]" />
                        <h5 className="font-bold text-sm mt-4">History Log Empty</h5>
                        <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">Run automation jobs to record runs.</p>
                      </div>
                    ) : (
                      taskHistory.map((task) => (
                        <div
                          key={task.id}
                          onClick={() => selectTaskFromHistory(task.id)}
                          className="p-5 bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-xl cursor-pointer hover:shadow-md transition-all duration-200 flex flex-col md:flex-row justify-between items-start md:items-center gap-4"
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-3">
                              <span className={`status-pill ${task.status}`}>{task.status}</span>
                              <span className="text-[10px] text-slate-500 dark:text-zinc-400 font-bold font-mono uppercase">{task.id}</span>
                              <span className="text-xs text-slate-500 dark:text-zinc-400 font-medium">{new Date(task.started_at).toLocaleString()}</span>
                            </div>
                            <p className="font-semibold text-sm mt-2 truncate leading-relaxed">{task.prompt}</p>
                            {task.result_summary && (
                              <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1 leading-relaxed truncate">{task.result_summary}</p>
                            )}
                          </div>
                          <button className="flex items-center gap-2 border border-slate-200 dark:border-zinc-800 hover:border-[#2563EB] dark:hover:border-[#60A5FA] px-4 py-2 rounded-xl text-xs font-semibold transition-all">
                            <RotateCcw className="w-3.5 h-3.5" />
                            Replay Run
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                )}

                {/* SETTINGS CARD OPTIONS */}
                {activeTab === 'settings' && (
                  <div className="max-w-xl mx-auto">
                    <div className="p-6 bg-white dark:bg-[#18181B] border border-slate-200/50 dark:border-zinc-800/50 rounded-2xl shadow-sm">
                      <h4 className="font-extrabold text-sm uppercase tracking-wider text-slate-500 dark:text-zinc-400 mb-6 pb-2 border-b border-slate-100 dark:border-zinc-800/50">Agent Configurations</h4>
                      
                      <form onSubmit={handleApplySettings} className="flex flex-col gap-5">
                        {/* LLM Provider Toggle */}
                        <div className="flex flex-col gap-2">
                          <label className="text-xs font-bold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Active LLM Provider</label>
                          <select
                            value={provider}
                            onChange={e => setProvider(e.target.value)}
                            className="w-full bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-xl px-4 py-3 text-xs outline-none text-[#0F172A] dark:text-[#FAFAFA] font-semibold"
                          >
                            <option value="gemini">Google Gemini</option>
                            <option value="groq">Groq (OpenAI-compatible Llama)</option>
                            <option value="mistral">Mistral AI</option>
                          </select>
                        </div>

                        {/* API Keys Configuration */}
                        <div className="flex flex-col gap-4 border-t border-slate-100 dark:border-zinc-800/50 pt-4">
                          <div className="flex flex-col gap-2">
                            <label className="text-xs font-bold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Gemini API Key</label>
                            <input
                              type="password"
                              placeholder="Enter GEMINI_API_KEY"
                              value={geminiKey}
                              onChange={e => setGeminiKey(e.target.value)}
                              className="w-full bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-xl px-4 py-3 text-xs outline-none font-medium placeholder-slate-400"
                            />
                          </div>

                          <div className="flex flex-col gap-2">
                            <label className="text-xs font-bold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Groq API Key</label>
                            <input
                              type="password"
                              placeholder="Enter GROQ_API_KEY"
                              value={groqKey}
                              onChange={e => setGroqKey(e.target.value)}
                              className="w-full bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-xl px-4 py-3 text-xs outline-none font-medium placeholder-slate-400"
                            />
                          </div>

                          <div className="flex flex-col gap-2">
                            <label className="text-xs font-bold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Mistral API Key</label>
                            <input
                              type="password"
                              placeholder="Enter MISTRAL_API_KEY"
                              value={mistralKey}
                              onChange={e => setMistralKey(e.target.value)}
                              className="w-full bg-slate-50 dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-xl px-4 py-3 text-xs outline-none font-medium placeholder-slate-400"
                            />
                          </div>
                        </div>

                        {/* Browser Headless Mode Toggle */}
                        <div className="flex justify-between items-center border-t border-slate-100 dark:border-zinc-800/50 pt-4">
                          <div>
                            <label className="text-xs font-bold uppercase tracking-wider">Playwright Headless Execution</label>
                            <p className="text-[10px] text-slate-500 dark:text-zinc-400 mt-1 leading-normal">
                              Run Chromium browser hidden in background (uncheck to show real browser window).
                            </p>
                          </div>
                          <input
                            type="checkbox"
                            checked={headless}
                            onChange={e => setHeadless(e.target.checked)}
                            className="w-5 h-5 accent-light-primary"
                          />
                        </div>

                        {/* Submit */}
                        <button
                          type="submit"
                          className="bg-[#2563EB] text-white font-bold text-xs py-3 rounded-xl hover:opacity-90 transition-opacity mt-4"
                        >
                          Apply Config Keys
                        </button>
                      </form>
                    </div>
                  </div>
                )}

              </motion.div>
            </AnimatePresence>
          </main>


        </div>

        {/* 5. Bottom Dock: Task Control Bar */}
        {activeTab === 'tasks' && activeTask && (
          <div className="h-[75px] shrink-0 bg-white/95 dark:bg-[#18181B]/95 border-t border-slate-200/50 dark:border-zinc-800/50 flex items-center justify-between px-8 z-30 shadow-2xl backdrop-blur-md">
            <div className="flex items-center gap-4">
              <div className="flex flex-col">
                <span className="text-[10px] font-bold text-slate-500 dark:text-zinc-400 uppercase tracking-wider">Current Running Step</span>
                <span className="text-xs font-semibold mt-0.5">
                  {actions.length > 0 ? actions[actions.length - 1].description : "Loading..."}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {activeTask.status === 'running' && (
                <button
                  onClick={() => stopTask(activeTask.id)}
                  className="bg-[#EF4444] hover:opacity-90 transition-opacity text-white text-xs font-bold px-5 py-2.5 rounded-xl shadow-md"
                >
                  Cancel Automation
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Command Palette (Ctrl + K modal overlay) */}
      <AnimatePresence>
        {showCommandPalette && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[200] flex items-center justify-center p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-lg bg-white dark:bg-[#18181B] border border-slate-200 dark:border-zinc-800 rounded-2xl shadow-2xl overflow-hidden"
            >
              <div className="p-4 border-b border-slate-100 dark:border-zinc-800/50 flex items-center gap-3">
                <Search className="w-4 h-4 text-slate-500 dark:text-zinc-400" />
                <input
                  type="text"
                  placeholder="Type a navigation command (e.g. settings, dashboard, tasks)..."
                  autoFocus
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      const val = (e.target as HTMLInputElement).value.toLowerCase().trim();
                      if (val === 'settings') setActiveTab('settings');
                      else if (val === 'dashboard') setActiveTab('dashboard');
                      else if (val === 'tasks') setActiveTab('tasks');
                      else if (val === 'browser') setActiveTab('browser');
                      else if (val === 'reports') setActiveTab('reports');
                      else if (val === 'history') setActiveTab('history');
                      else showToast(`Command "${val}" not recognized`, "info");
                      setShowCommandPalette(false);
                    } else if (e.key === 'Escape') {
                      setShowCommandPalette(false);
                    }
                  }}
                  className="flex-1 bg-transparent border-0 outline-none text-xs text-[#0F172A] dark:text-[#FAFAFA]"
                />
                <button
                  onClick={() => setShowCommandPalette(false)}
                  className="text-[10px] bg-slate-100 dark:bg-zinc-800 px-2 py-1 rounded text-slate-500 dark:text-zinc-400"
                >
                  Esc
                </button>
              </div>
              <div className="p-3 text-[10px] text-slate-500 dark:text-zinc-400 font-semibold uppercase tracking-wider bg-slate-50 dark:bg-zinc-900/40">
                Quick Shortcuts
              </div>
              <div className="flex flex-col p-2 text-xs">
                {[
                  { cmd: 'settings', desc: 'Go to Settings Panel' },
                  { cmd: 'dashboard', desc: 'Go to Agent Dashboard' },
                  { cmd: 'tasks', desc: 'View Active Tasks Port' },
                  { cmd: 'browser', desc: 'Open DOM Inspector' },
                ].map((s, idx) => (
                  <div
                    key={idx}
                    onClick={() => {
                      setActiveTab(s.cmd as any);
                      setShowCommandPalette(false);
                    }}
                    className="flex justify-between items-center px-3 py-2.5 hover:bg-slate-100/50 dark:hover:bg-zinc-800/30 rounded-xl cursor-pointer transition-colors"
                  >
                    <span className="font-bold font-mono">{s.cmd}</span>
                    <span className="text-slate-500 dark:text-zinc-400 text-[11px]">{s.desc}</span>
                  </div>
                ))}
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Reports Page Content Overlay (if selected tab is report) */}
      {activeTab === 'reports' && (
        <div className="hidden">
          {/* Keep state referenced */}
          <span>{reportContent}</span>
        </div>
      )}

    </div>
  );
}
