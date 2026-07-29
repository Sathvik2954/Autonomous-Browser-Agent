import React, { useState, useEffect, useRef } from 'react';
import {
  Sparkles,
  Play,
  Square,
  RotateCcw,
  CheckCircle2,
  AlertOctagon,
  Loader2,
  Sun,
  Moon,
  Download,
  Video,
  Clock3,
  History as HistoryIcon,
  Settings as SettingsIcon,
  FolderOpen,
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

type Tab = 'run' | 'history' | 'settings';

// Browser tasks (open a site, search, click around, summarize) are
// disabled -- the local model isn't reliable enough to drive them (see
// BROWSER_TASKS_DISABLED_MESSAGE in app/api/routes.py). Only organizer
// tasks (rename/tidy local files) are supported right now, so that's all
// that should be suggested here.
const SUGGESTED_PROMPTS = [
  { title: 'Organize my Downloads', desc: 'Rename the doc1 files in my Downloads folder based on their content.', icon: FolderOpen },
  { title: 'Tidy up a folder', desc: 'Organize the files on my Desktop by renaming them based on their content.', icon: FolderOpen },
  { title: 'Clean up documents', desc: 'Rename the generically-named docx files in my Documents folder.', icon: FolderOpen },
];

// FastAPI's HTTPException returns JSON like {"detail": "..."} -- reading
// the raw response body straight into a toast (the old behavior) showed
// the user that literal JSON wrapper instead of the message inside it.
// Falls back to the raw text if the body isn't JSON-shaped for some reason.
async function friendlyErrorText(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed.detail === 'string') return parsed.detail;
  } catch {
    // not JSON -- fall through to the raw text below
  }
  return text;
}

const STATUS_STYLES: Record<string, string> = {
  running: 'bg-[#F59E0B]/15 text-[#B45309] dark:bg-[#FBBF24]/15 dark:text-[#FBBF24]',
  completed: 'bg-[#10B981]/15 text-[#047857] dark:bg-[#34D399]/15 dark:text-[#34D399]',
  failed: 'bg-[#EF4444]/15 text-[#B91C1C] dark:bg-[#F87171]/15 dark:text-[#F87171]',
  stopped: 'bg-[#78716C]/15 text-[#57534E] dark:bg-[#A8A29E]/15 dark:text-[#A8A29E]',
};

function StatusPill({ status }: { status: string }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.stopped;
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-base font-bold capitalize ${style}`}>
      {status === 'running' && <Loader2 className="w-3 h-3 animate-spin" />}
      {status === 'completed' && <CheckCircle2 className="w-3 h-3" />}
      {status === 'failed' && <AlertOctagon className="w-3 h-3" />}
      {status}
    </span>
  );
}

// Wisp's mark: a small drifting flame/spark, standing in for the app's name
// instead of a generic icon-in-a-box logo.
function WispMark({ className = 'w-8 h-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="wispGradient" x1="6" y1="4" x2="26" y2="29" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FB923C" />
          <stop offset="1" stopColor="#F97316" />
        </linearGradient>
      </defs>
      <path
        d="M17.5 2.6c-5.6 5.8-8.3 11-8.3 15.6 0 5.4 4.2 9.5 9 9.5 4.6 0 8.3-3.5 8.3-8 0-3-1.7-5.3-4-7.6.1 2.6-1.2 4.5-3 4.5-1.9 0-2.8-1.6-2.8-3.5 0-3.2 2.2-6 3.6-8.8-1-.6-1.9-1.2-2.8-1.7Z"
        fill="url(#wispGradient)"
      />
      <circle cx="23.5" cy="7" r="1.6" fill="#FCD34D" />
      <circle cx="9" cy="6.5" r="1" fill="#FCD34D" opacity="0.8" />
    </svg>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('run');
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('theme');
    return (saved as 'light' | 'dark') || 'light';
  });

  // Task & polling state
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<TaskRecord | null>(null);
  const [actions, setActions] = useState<TaskAction[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [extractedData, setExtractedData] = useState<any[]>([]);
  const [videoExists, setVideoExists] = useState(false);
  const [latestScreenshotUrl, setLatestScreenshotUrl] = useState<string | null>(null);
  const [inspectedStep, setInspectedStep] = useState<number | null>(null);

  // Settings
  const [headless, setHeadless] = useState(true);

  // General UI state
  const [promptValue, setPromptValue] = useState('');
  const [taskHistory, setTaskHistory] = useState<TaskRecord[]>([]);
  const [toasts, setToasts] = useState<{ id: string; message: string; type: 'success' | 'info' | 'error' }[]>([]);

  // Auto-scrolling the activity log: scrollIntoView() on a sentinel div
  // (the previous approach) also scrolls ancestor containers -- including
  // the whole page -- to bring it into view, which fights the user the
  // moment they try to scroll up while a task is still polling every 1.5s.
  // Scrolling the log panel's own scrollTop directly, and only when the
  // user hasn't scrolled away from the bottom themselves, keeps the
  // autoscroll contained to the panel and lets the user actually read
  // older entries without being yanked back down.
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  const handleLogsScroll = () => {
    const el = logsContainerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distanceFromBottom < 32;
  };

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') root.classList.add('dark');
    else root.classList.remove('dark');
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    fetchTaskHistory();
  }, []);

  useEffect(() => {
    let intervalId: any = null;
    if (activeTaskId) {
      intervalId = setInterval(pollActiveTaskDetails, 1500);
      pollActiveTaskDetails();
    }
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [activeTaskId]);

  useEffect(() => {
    const el = logsContainerRef.current;
    if (el && stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [logs]);

  const showToast = (message: string, type: 'success' | 'info' | 'error' = 'info') => {
    const id = Math.random().toString(36).substring(7);
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  };

  const fetchTaskHistory = async () => {
    try {
      const response = await fetch('/api/tasks');
      if (response.ok) setTaskHistory(await response.json());
    } catch (e) {
      console.error('Error fetching history:', e);
    }
  };

  const resetRunView = () => {
    setActiveTaskId(null);
    setActiveTask(null);
    setActions([]);
    setLogs([]);
    setExtractedData([]);
    setVideoExists(false);
    setLatestScreenshotUrl(null);
    setInspectedStep(null);
    stickToBottomRef.current = true;
  };

  const startTask = async (promptText: string) => {
    if (!promptText.trim()) return;
    try {
      showToast("Okay, on it!", 'info');
      const response = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: promptText, headless }),
      });
      if (response.ok) {
        const data = await response.json();
        resetRunView();
        setActiveTaskId(data.task_id);
        setPromptValue('');
        setActiveTab('run');
        fetchTaskHistory();
      } else {
        showToast(`Couldn't start that: ${await friendlyErrorText(response)}`, 'error');
      }
    } catch (e) {
      showToast('Connection to the backend failed', 'error');
    }
  };

  const stopTask = async (id: string) => {
    try {
      const response = await fetch(`/api/tasks/${id}/stop`, { method: 'POST' });
      if (response.ok) showToast('Stopping...', 'info');
    } catch (e) {
      console.error(e);
    }
  };

  const resumeTask = async (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    try {
      showToast('Picking up where that left off...', 'info');
      const response = await fetch(`/api/tasks/${id}/resume`, { method: 'POST' });
      if (response.ok) {
        const data = await response.json();
        resetRunView();
        setActiveTaskId(data.task_id);
        setActiveTab('run');
        fetchTaskHistory();
      } else {
        showToast(`Couldn't resume that: ${await friendlyErrorText(response)}`, 'error');
      }
    } catch (e) {
      showToast('Connection to the backend failed', 'error');
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
        setVideoExists(data.video_exists);
        if (data.latest_screenshot) setLatestScreenshotUrl(data.latest_screenshot);

        if (['completed', 'failed', 'stopped'].includes(data.task.status)) {
          showToast(
            data.task.status === 'completed' ? 'All done!' : `Run ${data.task.status}.`,
            data.task.status === 'completed' ? 'success' : 'error'
          );
          setActiveTaskId(null);
          fetchTaskHistory();
        }
      }
    } catch (e) {
      console.error('Polling error:', e);
    }
  };

  const selectTaskFromHistory = (id: string) => {
    resetRunView();
    setActiveTaskId(id);
    setActiveTab('run');
  };

  const exportData = (format: string) => {
    const id = activeTask?.id;
    if (!id) return;
    window.open(`/api/tasks/${id}/export/${format}`);
  };

  const handleApplySettings = (e: React.FormEvent) => {
    e.preventDefault();
    showToast('Settings updated', 'success');
  };

  const isViewingRun = activeTask !== null;
  const screenshotSrc = inspectedStep !== null && activeTask
    ? `/api/tasks/${activeTask.id}/screenshot?step=${inspectedStep}&cb=${Date.now()}`
    : latestScreenshotUrl
      ? `${latestScreenshotUrl}&cb=${Date.now()}`
      : null;

  return (
    <div className="min-h-screen bg-[#FFFBF5] dark:bg-[#1C1917] text-[#292524] dark:text-[#FAFAF9]">
      {/* Toasts */}
      <div className="fixed top-5 right-5 z-[100] flex flex-col gap-2.5">
        <AnimatePresence>
          {toasts.map(t => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: -16, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className={`flex items-center gap-2.5 px-4 py-3 rounded-2xl border shadow-lg min-w-[260px] max-w-[380px] font-medium text-lg
                ${t.type === 'success' ? 'bg-[#10B981]/10 border-[#10B981]/30 text-[#047857] dark:text-[#34D399]' : ''}
                ${t.type === 'error' ? 'bg-[#EF4444]/10 border-[#EF4444]/30 text-[#B91C1C] dark:text-[#F87171]' : ''}
                ${t.type === 'info' ? 'bg-[#F97316]/10 border-[#F97316]/30 text-[#C2410C] dark:text-[#FB923C]' : ''}
              `}
            >
              {t.type === 'success' && <CheckCircle2 className="w-4 h-4 shrink-0" />}
              {t.type === 'error' && <AlertOctagon className="w-4 h-4 shrink-0" />}
              {t.type === 'info' && <Sparkles className="w-4 h-4 shrink-0" />}
              {t.message}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Top bar */}
      <header className="sticky top-0 z-20 bg-[#FFFBF5]/90 dark:bg-[#1C1917]/90 backdrop-blur-md border-b border-[#F0E4D4] dark:border-[#44403C]">
        <div className="w-full px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <WispMark className="w-9 h-9" />
            <span className="font-extrabold text-2xl tracking-tight">Wisp</span>
          </div>

          <nav className="flex items-center gap-1 bg-white/60 dark:bg-white/5 border border-[#F0E4D4] dark:border-[#44403C] rounded-full p-1">
            {[
              { id: 'run' as Tab, label: 'Run', icon: Sparkles },
              { id: 'history' as Tab, label: 'History', icon: HistoryIcon },
              { id: 'settings' as Tab, label: 'Settings', icon: SettingsIcon },
            ].map(item => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={`flex items-center gap-1.5 px-4 py-1.5 rounded-full text-lg font-semibold transition-all ${
                    isActive
                      ? 'bg-[#F97316] text-white shadow-sm'
                      : 'text-[#78716C] dark:text-[#A8A29E] hover:text-[#292524] dark:hover:text-[#FAFAF9]'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {item.label}
                </button>
              );
            })}
          </nav>

          <button
            onClick={() => setTheme(prev => (prev === 'light' ? 'dark' : 'light'))}
            className="w-9 h-9 rounded-full border border-[#F0E4D4] dark:border-[#44403C] bg-white/60 dark:bg-white/5 hover:bg-white dark:hover:bg-white/10 flex items-center justify-center transition-all"
          >
            {theme === 'light' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
          </button>
        </div>
      </header>

      {/* Main content */}
      <main className="w-full px-8 py-10">
        <AnimatePresence mode="wait">
          <motion.div
            key={`${activeTab}-${isViewingRun}`}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.18 }}
          >
            {/* RUN TAB */}
            {activeTab === 'run' && !isViewingRun && (
              <div className="flex flex-col gap-6 max-w-4xl mx-auto py-4">
                <div className="text-center flex flex-col gap-2">
                  <h1 className="text-5xl font-extrabold tracking-tight">Hey! What can I help with?</h1>
                  <p className="text-lg text-[#78716C] dark:text-[#A8A29E]">
                    I can rename and tidy up generically-named files on your computer based on their
                    content -- just tell me which folder, in plain language.
                  </p>
                </div>

                <div className="p-2 bg-white dark:bg-[#292524] border border-[#F0E4D4] dark:border-[#44403C] rounded-3xl shadow-lg shadow-[#F97316]/5 flex flex-col gap-1">
                  <textarea
                    value={promptValue}
                    onChange={e => setPromptValue(e.target.value)}
                    placeholder="e.g. Rename the doc1 files in my Downloads folder based on their content"
                    className="w-full h-28 bg-transparent text-lg p-4 outline-none resize-none font-medium placeholder-[#A8A29E]"
                  />
                  <div className="flex justify-between items-center px-3 py-2 border-t border-[#F0E4D4] dark:border-[#44403C]">
                    <span className="text-base text-[#78716C] dark:text-[#A8A29E] flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-[#F97316]" />
                      Autonomous agent
                    </span>
                    <button
                      onClick={() => startTask(promptValue)}
                      disabled={!promptValue.trim()}
                      className="flex items-center gap-2 bg-[#F97316] hover:bg-[#EA580C] text-white px-5 py-2.5 rounded-full text-lg font-bold shadow-md shadow-[#F97316]/30 transition-all disabled:opacity-40 disabled:pointer-events-none"
                    >
                      <Play className="w-3.5 h-3.5 fill-current" />
                      Let's go
                    </button>
                  </div>
                </div>

                <div className="px-4 py-3 bg-[#F97316]/5 dark:bg-[#F97316]/10 border border-[#F97316]/20 rounded-2xl text-base text-[#57534E] dark:text-[#D6D3D1] leading-relaxed">
                  <span className="font-bold text-[#F97316]">Tip:</span> be specific -- name the site or
                  what to search for, and what to extract. For file organizing, name the folder explicitly
                  (e.g. "in my Downloads folder") -- I won't guess one on my own.
                </div>

                <div className="flex flex-col gap-3">
                  <h2 className="text-base font-bold uppercase tracking-wider text-[#78716C] dark:text-[#A8A29E]">
                    Need inspiration?
                  </h2>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {SUGGESTED_PROMPTS.map((item, idx) => {
                      const Icon = item.icon;
                      return (
                        <button
                          key={idx}
                          onClick={() => setPromptValue(item.desc)}
                          className="text-left p-4 bg-white dark:bg-[#292524] border border-[#F0E4D4] dark:border-[#44403C] rounded-2xl hover:border-[#F97316]/40 hover:shadow-md transition-all flex items-start gap-3"
                        >
                          <div className="w-8 h-8 shrink-0 rounded-xl bg-[#F97316]/10 flex items-center justify-center text-[#F97316]">
                            <Icon className="w-4 h-4" />
                          </div>
                          <div>
                            <h3 className="font-bold text-base">{item.title}</h3>
                            <p className="text-base text-[#78716C] dark:text-[#A8A29E] mt-0.5 leading-relaxed">{item.desc}</p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* RUN TAB -- viewing an active/finished run */}
            {activeTab === 'run' && isViewingRun && activeTask && (
              <div className="flex flex-col gap-5">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2.5 flex-wrap">
                      <StatusPill status={activeTask.status} />
                      <span className="text-base font-mono text-[#A8A29E]">{activeTask.id}</span>
                    </div>
                    <p className="font-bold text-2xl mt-1.5 leading-snug">{activeTask.prompt}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {activeTask.status === 'running' && (
                      <button
                        onClick={() => stopTask(activeTask.id)}
                        className="flex items-center gap-1.5 bg-[#EF4444] hover:bg-[#DC2626] text-white text-base font-bold px-4 py-2 rounded-full shadow-sm transition-all"
                      >
                        <Square className="w-3 h-3 fill-current" />
                        Stop
                      </button>
                    )}
                    <button
                      onClick={resetRunView}
                      className="flex items-center gap-1.5 border border-[#F0E4D4] dark:border-[#44403C] hover:border-[#F97316]/40 text-base font-bold px-4 py-2 rounded-full transition-all"
                    >
                      New task
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-5">
                  {/* Left: screenshot + activity feed */}
                  <div className="flex flex-col gap-5 min-w-0">
                    <div className="bg-white dark:bg-[#292524] border border-[#F0E4D4] dark:border-[#44403C] rounded-3xl overflow-hidden shadow-sm">
                      <div className="aspect-video bg-[#292524] dark:bg-black/40 flex items-center justify-center overflow-hidden">
                        {screenshotSrc ? (
                          <img src={screenshotSrc} alt="Latest step" className="max-w-full max-h-full object-contain" />
                        ) : (
                          <div className="text-center text-[#A8A29E] flex flex-col items-center gap-3 p-8">
                            <Loader2 className="w-8 h-8 animate-spin" />
                            <p className="text-base font-medium">Getting started...</p>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="bg-white dark:bg-[#292524] border border-[#F0E4D4] dark:border-[#44403C] rounded-3xl overflow-hidden shadow-sm">
                      <div className="px-5 py-3 border-b border-[#F0E4D4] dark:border-[#44403C] flex items-center gap-2">
                        <Clock3 className="w-4 h-4 text-[#F97316]" />
                        <span className="font-bold text-base uppercase tracking-wider text-[#78716C] dark:text-[#A8A29E]">
                          What I'm doing
                        </span>
                      </div>
                      <div
                        ref={logsContainerRef}
                        onScroll={handleLogsScroll}
                        className="max-h-64 overflow-y-auto p-4 flex flex-col gap-2"
                      >
                        {logs.length === 0 ? (
                          <p className="text-base text-[#A8A29E] py-6 text-center">Waking up...</p>
                        ) : (
                          logs.map(log => (
                            <div key={log.id} className="flex gap-2.5 text-base leading-relaxed">
                              <span className="text-[#A8A29E] font-mono shrink-0">
                                {new Date(log.timestamp).toLocaleTimeString([], { hour12: false })}
                              </span>
                              <span
                                className={
                                  log.level === 'error'
                                    ? 'text-[#B91C1C] dark:text-[#F87171] font-medium'
                                    : log.level === 'warning'
                                      ? 'text-[#B45309] dark:text-[#FBBF24] font-medium'
                                      : log.level === 'thought'
                                        ? 'italic text-[#57534E] dark:text-[#D6D3D1]'
                                        : 'text-[#292524] dark:text-[#E7E5E4]'
                                }
                              >
                                {log.message}
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Right: result + timeline */}
                  <div className="flex flex-col gap-5">
                    {activeTask.result_summary && (
                      <div className="p-4 bg-[#10B981]/5 dark:bg-[#10B981]/10 border border-[#10B981]/25 rounded-3xl flex flex-col gap-2">
                        <div className="flex items-center gap-2 text-base font-bold uppercase tracking-wider text-[#047857] dark:text-[#34D399]">
                          <CheckCircle2 className="w-4 h-4" />
                          Result
                        </div>
                        <p className="text-base leading-relaxed whitespace-pre-wrap text-[#292524] dark:text-[#E7E5E4] max-h-56 overflow-y-auto">
                          {activeTask.result_summary}
                        </p>
                        <div className="flex flex-wrap gap-2 pt-1">
                          {extractedData.length > 0 && (
                            <>
                              <button onClick={() => exportData('csv')} className="flex items-center gap-1.5 text-base font-bold px-3 py-1.5 rounded-full border border-[#10B981]/30 text-[#047857] dark:text-[#34D399] hover:bg-[#10B981]/10 transition-all">
                                <Download className="w-3 h-3" /> CSV
                              </button>
                              <button onClick={() => exportData('json')} className="flex items-center gap-1.5 text-base font-bold px-3 py-1.5 rounded-full border border-[#10B981]/30 text-[#047857] dark:text-[#34D399] hover:bg-[#10B981]/10 transition-all">
                                <Download className="w-3 h-3" /> JSON
                              </button>
                            </>
                          )}
                          {videoExists && (
                            <a href={`/api/tasks/${activeTask.id}/video`} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 text-base font-bold px-3 py-1.5 rounded-full border border-[#10B981]/30 text-[#047857] dark:text-[#34D399] hover:bg-[#10B981]/10 transition-all">
                                <Video className="w-3 h-3" /> Recording
                              </a>
                          )}
                        </div>
                      </div>
                    )}

                    {activeTask.error && (
                      <div className="p-4 bg-[#EF4444]/5 dark:bg-[#EF4444]/10 border border-[#EF4444]/25 rounded-3xl flex flex-col gap-2">
                        <div className="flex items-center gap-2 text-base font-bold uppercase tracking-wider text-[#B91C1C] dark:text-[#F87171]">
                          <AlertOctagon className="w-4 h-4" />
                          Ran into a problem
                        </div>
                        <p className="text-base leading-relaxed text-[#292524] dark:text-[#E7E5E4]">{activeTask.error}</p>
                      </div>
                    )}

                    <div className="bg-white dark:bg-[#292524] border border-[#F0E4D4] dark:border-[#44403C] rounded-3xl overflow-hidden shadow-sm flex flex-col">
                      <div className="px-4 py-3 border-b border-[#F0E4D4] dark:border-[#44403C] flex justify-between items-center">
                        <span className="font-bold text-base uppercase tracking-wider text-[#78716C] dark:text-[#A8A29E]">Steps</span>
                        {inspectedStep !== null && (
                          <button onClick={() => setInspectedStep(null)} className="text-sm font-bold text-[#F97316]">
                            Back to live
                          </button>
                        )}
                      </div>
                      <div className="p-3 flex flex-col gap-2 max-h-72 overflow-y-auto">
                        {actions.length === 0 ? (
                          <p className="text-center py-8 text-[#A8A29E] text-base">Nothing yet.</p>
                        ) : (
                          actions.map(act => (
                            <button
                              key={act.id}
                              onClick={() => setInspectedStep(act.step)}
                              className={`text-left p-3 rounded-2xl transition-all flex gap-3 ${
                                inspectedStep === act.step
                                  ? 'bg-[#F97316]/10 border border-[#F97316]/30'
                                  : 'border border-transparent hover:bg-[#F97316]/5'
                              }`}
                            >
                              <div className="w-5 h-5 shrink-0 rounded-full bg-[#F97316]/15 text-[#C2410C] dark:text-[#FB923C] text-sm font-bold flex items-center justify-center mt-0.5">
                                {act.step}
                              </div>
                              <div className="min-w-0">
                                <p className="font-bold text-base uppercase text-[#C2410C] dark:text-[#FB923C]">{act.action_type}</p>
                                <p className="text-base text-[#78716C] dark:text-[#A8A29E] mt-0.5 leading-relaxed">{act.description}</p>
                              </div>
                            </button>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* HISTORY TAB */}
            {activeTab === 'history' && (
              <div className="max-w-5xl mx-auto flex flex-col gap-3">
                {taskHistory.length === 0 ? (
                  <div className="text-center py-20 bg-white dark:bg-[#292524] border border-[#F0E4D4] dark:border-[#44403C] rounded-3xl">
                    <HistoryIcon className="w-10 h-10 text-[#A8A29E] mx-auto stroke-[1.5]" />
                    <h3 className="font-bold text-lg mt-4">No runs yet</h3>
                    <p className="text-base text-[#78716C] dark:text-[#A8A29E] mt-1">Start something on the Run tab and it'll show up here.</p>
                  </div>
                ) : (
                  taskHistory.map(task => (
                    <div
                      key={task.id}
                      onClick={() => selectTaskFromHistory(task.id)}
                      className="p-4 bg-white dark:bg-[#292524] border border-[#F0E4D4] dark:border-[#44403C] rounded-2xl cursor-pointer hover:border-[#F97316]/40 hover:shadow-sm transition-all flex flex-col md:flex-row justify-between items-start md:items-center gap-3"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2.5 flex-wrap">
                          <StatusPill status={task.status} />
                          <span className="text-base text-[#A8A29E]">{new Date(task.started_at).toLocaleString()}</span>
                        </div>
                        <p className="font-semibold text-lg mt-1.5 truncate">{task.prompt}</p>
                        {task.result_summary && (
                          <p className="text-base text-[#78716C] dark:text-[#A8A29E] mt-0.5 truncate">{task.result_summary}</p>
                        )}
                      </div>
                      <button
                        onClick={e => resumeTask(task.id, e)}
                        className="flex items-center gap-1.5 border border-[#F0E4D4] dark:border-[#44403C] hover:border-[#F97316]/40 px-3.5 py-2 rounded-full text-base font-bold shrink-0 transition-all"
                      >
                        <RotateCcw className="w-3 h-3" />
                        Replay
                      </button>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* SETTINGS TAB */}
            {activeTab === 'settings' && (
              <div className="max-w-2xl mx-auto">
                <div className="p-6 bg-white dark:bg-[#292524] border border-[#F0E4D4] dark:border-[#44403C] rounded-3xl shadow-sm">
                  <h2 className="font-extrabold text-lg uppercase tracking-wider text-[#78716C] dark:text-[#A8A29E] mb-5 pb-3 border-b border-[#F0E4D4] dark:border-[#44403C]">
                    Settings
                  </h2>

                  <form onSubmit={handleApplySettings} className="flex flex-col gap-5">
                    <div className="flex flex-col gap-2">
                      <label className="text-base font-bold text-[#78716C] dark:text-[#A8A29E] uppercase tracking-wider">Model</label>
                      <div className="w-full bg-[#FFFBF5] dark:bg-[#1C1917] border border-[#F0E4D4] dark:border-[#44403C] rounded-2xl px-4 py-3 text-base font-mono">
                        qwen2.5:3b @ http://localhost:11434/v1 <span className="text-[#A8A29E]">(defaults)</span>
                      </div>
                      <p className="text-base text-[#78716C] dark:text-[#A8A29E] leading-normal">
                        This is the model that plans each step and names your files. Change it via
                        <code className="mx-1 px-1 py-0.5 bg-[#F0E4D4] dark:bg-[#44403C] rounded">OLLAMA_MODEL</code>
                        in <code className="px-1 py-0.5 bg-[#F0E4D4] dark:bg-[#44403C] rounded">.env</code>, then restart the backend.
                        Make sure Ollama is running (<code className="px-1 py-0.5 bg-[#F0E4D4] dark:bg-[#44403C] rounded">ollama serve</code>).
                      </p>
                    </div>

                    <div className="flex justify-between items-center border-t border-[#F0E4D4] dark:border-[#44403C] pt-4">
                      <div className="pr-4">
                        <label className="text-base font-bold uppercase tracking-wider">Show the browser window</label>
                        <p className="text-base text-[#78716C] dark:text-[#A8A29E] mt-1 leading-normal">
                          Off by default (runs hidden in the background). Turn on to watch it work in a real window.
                        </p>
                      </div>
                      <input
                        type="checkbox"
                        checked={headless === false}
                        onChange={e => setHeadless(!e.target.checked)}
                        className="w-5 h-5 accent-[#F97316] shrink-0"
                      />
                    </div>

                    <button
                      type="submit"
                      className="bg-[#F97316] hover:bg-[#EA580C] text-white font-bold text-lg py-3 rounded-full transition-all mt-2"
                    >
                      Save
                    </button>
                  </form>
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
