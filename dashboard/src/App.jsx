import React, { useState, useEffect } from 'react';
import { Upload, FileVideo, Sparkles, Youtube, Instagram, Share2, LogOut, ChevronDown, Check, Activity, LayoutDashboard, Settings, PlusCircle, History, Menu, X, Terminal, Shield, LayoutGrid, Image, Globe } from 'lucide-react';
import KeyInput from './components/KeyInput';
import MediaInput from './components/MediaInput';
import ResultCard from './components/ResultCard';
import ProcessingAnimation from './components/ProcessingAnimation';
// import Gallery from './components/Gallery';
import ThumbnailStudio from './components/ThumbnailStudio';
import JobHistory from './components/JobHistory';
import { getApiUrl } from './config';
import { BACKGROUND_OPTIONS, DEFAULT_HOOK_STYLE, DEFAULT_SUBTITLE_STYLE, FONT_OPTIONS } from './overlayOptions';
import { DEFAULT_SOCIAL_POST_SETTINGS, INSTAGRAM_SHARE_MODES, SOCIAL_PLATFORM_OPTIONS, TIKTOK_POST_MODES } from './socialOptions';

// Enhanced "Encryption" using XOR + Base64 with a Salt
// This is better than plain Base64 but still client-side.
const SECRET_KEY = import.meta.env.VITE_ENCRYPTION_KEY || "OpenShorts-Static-Salt-Change-Me";
const ENCRYPTION_PREFIX = "ENC:";

const encrypt = (text) => {
  if (!text) return '';
  try {
    const xor = text.split('').map((c, i) =>
      String.fromCharCode(c.charCodeAt(0) ^ SECRET_KEY.charCodeAt(i % SECRET_KEY.length))
    ).join('');
    return ENCRYPTION_PREFIX + btoa(xor);
  } catch (e) {
    console.error("Encryption failed", e);
    return text;
  }
};

const decrypt = (text) => {
  if (!text) return '';
  if (text.startsWith(ENCRYPTION_PREFIX)) {
    try {
      const raw = text.slice(ENCRYPTION_PREFIX.length);
      // Check if it's plain base64 or our custom XOR (simple try)
      const xor = atob(raw);
      const result = xor.split('').map((c, i) =>
        String.fromCharCode(c.charCodeAt(0) ^ SECRET_KEY.charCodeAt(i % SECRET_KEY.length))
      ).join('');
      return result;
    } catch (e) {
      // Fallback if decryption fails (might be old plain text)
      return '';
    }
  }
  // Backward compatibility: If no prefix, assume old plain text (or return empty if you want to force re-login)
  // For migration: Return text as is, so it populates the field, and next save will encrypt it.
  return text;
};

// Simple TikTok icon sine Lucide might not have it or it varies
const TikTokIcon = ({ size = 16, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

const UserProfileSelector = ({ profiles, selectedUserId, onSelect }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!profiles || profiles.length === 0) return null;

  const selectedProfile = profiles.find(p => p.username === selectedUserId) || profiles[0];

  return (
    <div className="relative z-50">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between bg-surface border border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-300 hover:bg-white/5 transition-colors min-w-[180px]"
      >
        <span className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-full bg-gradient-to-br from-primary to-purple-600 flex items-center justify-center text-[10px] font-bold text-white">
            {selectedProfile?.username?.substring(0, 1).toUpperCase() || "U"}
          </div>
          <span className="font-medium text-white truncate max-w-[100px]">{selectedProfile?.username || "Select User"}</span>
        </span>
        <ChevronDown size={14} className={`text-zinc-500 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute top-full mt-2 right-0 w-64 bg-[#1a1a1a] border border-white/10 rounded-xl shadow-2xl overflow-hidden">
          <div className="max-h-60 overflow-y-auto custom-scrollbar">
            {profiles.map((profile) => (
              <button
                key={profile.username}
                onClick={() => {
                  onSelect(profile.username);
                  setIsOpen(false);
                }}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors text-left group border-b border-white/5 last:border-0"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-purple-500/20 flex items-center justify-center text-xs font-bold text-white border border-white/10 shrink-0">
                    {profile.username.substring(0, 2).toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-zinc-200 group-hover:text-white transition-colors truncate">
                      {profile.username}
                    </div>
                    <div className="flex gap-2 mt-0.5">
                      {/* Status indicators */}
                      <div className={`flex items-center gap-1 text-[10px] ${profile.connected.includes('tiktok') ? 'text-zinc-300' : 'text-zinc-600'}`}>
                        <TikTokIcon size={10} />
                      </div>
                      <div className={`flex items-center gap-1 text-[10px] ${profile.connected.includes('instagram') ? 'text-pink-400' : 'text-zinc-600'}`}>
                        <Instagram size={10} />
                      </div>
                      <div className={`flex items-center gap-1 text-[10px] ${profile.connected.includes('youtube') ? 'text-red-400' : 'text-zinc-600'}`}>
                        <Youtube size={10} />
                      </div>
                    </div>
                  </div>
                </div>
                {selectedUserId === profile.username && <Check size={14} className="text-primary shrink-0" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// Mock polling function
const pollJob = async (jobId) => {
  const res = await fetch(getApiUrl(`/api/status/${jobId}`));
  if (!res.ok) throw new Error('Status check failed');
  return res.json();
};

const readErrorMessage = async (res) => {
  const text = await res.text();
  try {
    const json = JSON.parse(text);
    return json.detail || text;
  } catch (e) {
    return text;
  }
};

const readStoredJson = (key, fallback) => {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch (e) {
    return fallback;
  }
};

const readStoredSocialPostSettings = () => {
  try {
    const raw = localStorage.getItem('social_post_settings_v1');
    if (!raw) return DEFAULT_SOCIAL_POST_SETTINGS;
    const parsed = JSON.parse(raw);
    return {
      ...DEFAULT_SOCIAL_POST_SETTINGS,
      ...parsed,
      platforms: {
        ...DEFAULT_SOCIAL_POST_SETTINGS.platforms,
        ...(parsed.platforms || {}),
      },
    };
  } catch (e) {
    return DEFAULT_SOCIAL_POST_SETTINGS;
  }
};

const normalizeOllamaModelName = (value) => {
  const trimmed = (value || '').trim();
  if (!trimmed) return '';
  const aliasMap = {
    'gemma-3-12b': 'gemma3:12b',
    'gemma-3-12b:latest': 'gemma3:12b',
    'gemma3-12b': 'gemma3:12b',
    'gemma3-12b:latest': 'gemma3:12b',
  };
  return aliasMap[trimmed.toLowerCase()] || trimmed;
};

const TIGHT_EDIT_PRESET_OPTIONS = [
  {
    value: 'aggressive',
    label: 'Aggressive',
    description: 'Cuts pauses and filler words decisively. Best default for short-form.',
  },
  {
    value: 'balanced',
    label: 'Balanced',
    description: 'Less jumpy, keeps a little more breathing room.',
  },
  {
    value: 'very_aggressive',
    label: 'Very Aggressive',
    description: 'Removes even more silence and filler. Use when you want maximum pace.',
  },
  {
    value: 'off',
    label: 'Off',
    description: 'Keeps the original speech rhythm.',
  },
];

const DEFAULT_TIGHT_EDIT_SETTINGS = {
  preset: 'aggressive',
};

function App() {
  const [apiKey, setApiKey] = useState(localStorage.getItem('gemini_key') || '');
  const [llmProvider, setLlmProvider] = useState(localStorage.getItem('llm_provider') || 'gemini');
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState(() => {
    const stored = localStorage.getItem('ollama_base_url');
    if (!stored || stored === 'http://host.docker.internal:11434') {
      return 'http://127.0.0.1:11434';
    }
    return stored;
  });
  const [ollamaModel, setOllamaModelState] = useState(
    normalizeOllamaModelName(localStorage.getItem('ollama_model') || 'llama3.1:8b')
  );
  // Social API State - Load encrypted or plain
  const [uploadPostKey, setUploadPostKey] = useState(() => {
    const stored = localStorage.getItem('uploadPostKey_v3');
    if (stored) return decrypt(stored);
    return '';
  });
  // ElevenLabs API State - Load encrypted
  const [elevenLabsKey, setElevenLabsKey] = useState(() => {
    const stored = localStorage.getItem('elevenLabsKey_v1');
    if (stored) return decrypt(stored);
    return '';
  });

  const [uploadUserId, setUploadUserId] = useState(() => localStorage.getItem('uploadUserId') || '');
  const [userProfiles, setUserProfiles] = useState([]); // List of {username, connected: []}
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle, processing, complete, error
  const [jobState, setJobState] = useState('idle'); // queued, processing, partial, completed, failed
  const [results, setResults] = useState(null);
  const [logs, setLogs] = useState([]);
  const [logsVisible, setLogsVisible] = useState(true);
  const [processingMedia, setProcessingMedia] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard'); // dashboard, history, settings
  const [historyJobs, setHistoryJobs] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [cancelingJobId, setCancelingJobId] = useState(null);
  const [subtitleStyle, setSubtitleStyle] = useState(() => readStoredJson('subtitle_style_v1', DEFAULT_SUBTITLE_STYLE));
  const [hookStyle, setHookStyle] = useState(() => readStoredJson('hook_style_v1', DEFAULT_HOOK_STYLE));
  const [tightEditSettings, setTightEditSettings] = useState(() => readStoredJson('tight_edit_settings_v1', DEFAULT_TIGHT_EDIT_SETTINGS));
  const [socialPostSettings, setSocialPostSettings] = useState(() => readStoredSocialPostSettings());
  const [clipVideoOverrides, setClipVideoOverrides] = useState({});

  // Sync state for original video playback
  const [syncedTime, setSyncedTime] = useState(0);
  const [isSyncedPlaying, setIsSyncedPlaying] = useState(false);
  const [syncTrigger, setSyncTrigger] = useState(0);

  const handleClipPlay = (startTime) => {
    setSyncedTime(startTime);
    setIsSyncedPlaying(true);
    setSyncTrigger(prev => prev + 1);
  };

  const handleClipPause = () => {
    setIsSyncedPlaying(false);
  };

  const setOllamaModel = (value) => {
    setOllamaModelState(normalizeOllamaModelName(value));
  };

  const getClipVariantKey = (activeJobId, clip, fallbackIndex) => `${activeJobId}:${clip.clip_index ?? fallbackIndex}`;

  const updateClipVideoOverride = (activeJobId, clip, fallbackIndex, videoUrl) => {
    const key = getClipVariantKey(activeJobId, clip, fallbackIndex);
    setClipVideoOverrides((prev) => {
      if (!videoUrl) {
        if (!(key in prev)) {
          return prev;
        }
        const next = { ...prev };
        delete next[key];
        return next;
      }
      return { ...prev, [key]: videoUrl };
    });
  };

  const updateClipResult = (activeJobId, updatedClip) => {
    if (!updatedClip) return;
    setResults((prev) => {
      if (!prev?.clips?.length) return prev;
      return {
        ...prev,
        clips: prev.clips.map((clip, index) => (
          (clip.clip_index ?? index) === (updatedClip.clip_index ?? index)
            ? updatedClip
            : clip
        )),
      };
    });
    updateClipVideoOverride(activeJobId, updatedClip, updatedClip.clip_index ?? 0, null);
  };

  const buildProviderHeaders = (includeJson = false) => {
    const headers = {
      'X-LLM-Provider': llmProvider
    };

    if (llmProvider === 'gemini' && apiKey) {
      headers['X-Gemini-Key'] = apiKey;
    }

    if (llmProvider === 'ollama') {
      headers['X-Ollama-Base-Url'] = ollamaBaseUrl;
      headers['X-Ollama-Model'] = ollamaModel;
    }

    if (includeJson) {
      headers['Content-Type'] = 'application/json';
    }

    return headers;
  };

  const deriveProcessingMedia = (job) => {
    const request = job?.request;
    if (request?.type === 'url' && request?.url) {
      return { type: 'url', payload: request.url };
    }
    return null;
  };

  const mapApiStatusToUi = (apiStatus) => {
    if (apiStatus === 'cancelled') return 'error';
    if (apiStatus === 'failed') return 'error';
    if (apiStatus === 'completed') return 'complete';
    return 'processing';
  };

  useEffect(() => {
    // Encrypt Gemini Key too for consistency if desired, but user asked specifically about Social integration not saving well.
    // For now keeping gemini plain for compatibility unless requested.
    if (apiKey) localStorage.setItem('gemini_key', apiKey);
  }, [apiKey]);

  useEffect(() => {
    localStorage.setItem('llm_provider', llmProvider);
    localStorage.setItem('ollama_base_url', ollamaBaseUrl);
    localStorage.setItem('ollama_model', ollamaModel);
  }, [llmProvider, ollamaBaseUrl, ollamaModel]);

  useEffect(() => {
    localStorage.setItem('subtitle_style_v1', JSON.stringify(subtitleStyle));
  }, [subtitleStyle]);

  useEffect(() => {
    localStorage.setItem('hook_style_v1', JSON.stringify(hookStyle));
  }, [hookStyle]);

  useEffect(() => {
    localStorage.setItem('tight_edit_settings_v1', JSON.stringify(tightEditSettings));
  }, [tightEditSettings]);

  useEffect(() => {
    localStorage.setItem('social_post_settings_v1', JSON.stringify(socialPostSettings));
  }, [socialPostSettings]);

  useEffect(() => {
    if (uploadPostKey) {
      localStorage.setItem('uploadPostKey_v3', encrypt(uploadPostKey));
    }
    if (uploadUserId) {
      localStorage.setItem('uploadUserId', uploadUserId);
    }
  }, [uploadPostKey, uploadUserId]);

  useEffect(() => {
    if (elevenLabsKey) {
      localStorage.setItem('elevenLabsKey_v1', encrypt(elevenLabsKey));
    }
  }, [elevenLabsKey]);

  useEffect(() => {
    if (uploadPostKey && userProfiles.length === 0) {
      fetchUserProfiles();
    }
  }, [uploadPostKey]);

  useEffect(() => {
    let interval;
    if (status === 'processing' && jobId) {
      interval = setInterval(async () => {
        try {
          const data = await pollJob(jobId);
          console.log("Job status:", data);

          // Update results if available (real-time)
          if (data.result) {
            setResults(data.result);
          }
          if (data.logs) {
            setLogs(data.logs);
          }
          if (data.job_state) {
            setJobState(data.job_state);
          }

          if (data.status === 'completed') {
            setStatus('complete');
            if (data.job_state) {
              setJobState(data.job_state);
            }
            clearInterval(interval);
          } else if (data.status === 'failed' || data.status === 'cancelled') {
            setStatus('error');
            const errorMsg = data.error || (data.logs && data.logs.length > 0 ? data.logs[data.logs.length - 1] : "Process failed");
            setLogs(prev => [...prev, "Error: " + errorMsg]);
            setJobState(data.job_state || data.status || 'failed');
            clearInterval(interval);
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [status, jobId]);

  const fetchJobHistory = async () => {
    setHistoryLoading(true);
    setHistoryError('');
    try {
      const res = await fetch(getApiUrl('/api/jobs/history'));
      if (!res.ok) {
        throw new Error('Failed to load job history');
      }
      const data = await res.json();
      setHistoryJobs(data.jobs || []);
    } catch (e) {
      setHistoryError(e.message || 'Failed to load job history');
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'history') {
      fetchJobHistory();
    }
  }, [activeTab]);


  const fetchUserProfiles = async () => {
    if (!uploadPostKey) return;
    try {
      const res = await fetch(getApiUrl('/api/social/user'), {
        headers: { 'X-Upload-Post-Key': uploadPostKey }
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      if (data.profiles && data.profiles.length > 0) {
        setUserProfiles(data.profiles);
        // Auto select first if none selected
        if (!uploadUserId || !data.profiles.some((profile) => profile.username === uploadUserId)) {
          setUploadUserId(data.profiles[0].username);
        }
      } else {
        setUserProfiles([]);
        alert(data.error || "No profiles found for this API Key.");
      }
    } catch (e) {
      alert(`Error fetching User Profiles: ${e.message}`);
      console.error(e);
    }
  };

  const handleProcess = async (data) => {
    setStatus('processing');
    setJobState('queued');
    setLogs(["Starting process..."]);
    setResults(null);
    setClipVideoOverrides({});
    setProcessingMedia(data);

    try {
      let body;
      const headers = buildProviderHeaders(data.type === 'url');

      if (data.type === 'url') {
        body = JSON.stringify({
          url: data.payload,
          interview_mode: !!data.options?.interviewMode,
          allow_long_clips: !!data.options?.allowLongClips,
          max_clips: Number(data.options?.maxClips) || 10,
          tight_edit_preset: tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset,
        });
      } else {
        const formData = new FormData();
        formData.append('file', data.payload);
        formData.append('interview_mode', data.options?.interviewMode ? 'true' : 'false');
        formData.append('allow_long_clips', data.options?.allowLongClips ? 'true' : 'false');
        formData.append('max_clips', String(Number(data.options?.maxClips) || 10));
        formData.append('tight_edit_preset', tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset);
        body = formData;
      }

      const res = await fetch(getApiUrl('/api/process'), {
        method: 'POST',
        headers: data.type === 'url' ? headers : { ...headers },
        body
      });

      if (!res.ok) throw new Error(await readErrorMessage(res));
      const resData = await res.json();
      setJobId(resData.job_id);
      fetchJobHistory();

    } catch (e) {
      setStatus('error');
      setJobState('failed');
      setLogs(l => [...l, `Error starting job: ${e.message}`]);
    }
  };

  const handleReset = () => {
    setStatus('idle');
    setJobState('idle');
    setJobId(null);
    setResults(null);
    setClipVideoOverrides({});
    setLogs([]);
    setProcessingMedia(null);
  };

  const handleOpenJob = async (job) => {
    try {
      const data = await pollJob(job.job_id);
      setJobId(job.job_id);
      setResults(data.result || job.result || null);
      setLogs(data.logs || job.logs || []);
      setProcessingMedia(deriveProcessingMedia(job));
      setJobState(data.job_state || job.status || 'completed');
      setStatus(mapApiStatusToUi(data.status));
      setActiveTab('dashboard');
    } catch (e) {
      alert(`Failed to open job: ${e.message}`);
    }
  };

  const handleResumeJob = async (job) => {
    try {
      const res = await fetch(getApiUrl(`/api/jobs/${job.job_id}/resume`), {
        method: 'POST',
        headers: buildProviderHeaders(true),
        body: JSON.stringify({
          provider: llmProvider,
          ollama_base_url: ollamaBaseUrl,
          ollama_model: ollamaModel,
          tight_edit_preset: tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset,
        })
      });

      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }

      const data = await res.json();
      setJobId(data.job_id);
      setStatus('processing');
      setJobState('queued');
      setResults(job.result || null);
      setLogs((job.logs || []).concat([`Job ${job.job_id} resumed and queued.`]));
      setProcessingMedia(deriveProcessingMedia(job));
      setActiveTab('dashboard');
      fetchJobHistory();
    } catch (e) {
      alert(`Failed to resume job: ${e.message}`);
    }
  };

  const handleCancelJob = async (job) => {
    setCancelingJobId(job.job_id);
    try {
      const res = await fetch(getApiUrl(`/api/jobs/${job.job_id}/cancel`), {
        method: 'POST',
      });

      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }

      const data = await res.json();
      if (job.job_id === jobId) {
        setLogs(data.logs || []);
        setResults(data.result || results);
        if (data.status === 'cancelled') {
          setStatus('error');
          setJobState('cancelled');
        }
      }
      fetchJobHistory();
    } catch (e) {
      alert(`Failed to cancel job: ${e.message}`);
    } finally {
      setCancelingJobId(null);
    }
  };

  // --- UI Components ---

  const Sidebar = () => (
    <div className="w-20 lg:w-64 bg-surface border-r border-white/5 flex flex-col h-full shrink-0 transition-all duration-300">
      <div className="p-6 flex items-center gap-3">
        <div className="w-8 h-8 bg-white/5 rounded-lg flex items-center justify-center shrink-0 overflow-hidden border border-white/5">
          <img src="/logo-openshorts.png" alt="Logo" className="w-full h-full object-cover" />
        </div>
        <span className="font-bold text-lg text-white hidden lg:block tracking-tight">OpenShorts</span>
      </div>

      <nav className="flex-1 px-4 py-4 space-y-2">
        <button
          onClick={() => setActiveTab('dashboard')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'dashboard' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <LayoutDashboard size={20} />
          <span className="font-medium hidden lg:block">Dashboard</span>
        </button>

        <button
          onClick={() => setActiveTab('thumbnails')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'thumbnails' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <Image size={20} />
          <span className="font-medium hidden lg:block">YouTube Studio</span>
        </button>

        <button
          onClick={() => setActiveTab('history')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'history' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <History size={20} />
          <span className="font-medium hidden lg:block">History</span>
        </button>

        <button
          onClick={() => setActiveTab('settings')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'settings' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <Settings size={20} />
          <span className="font-medium hidden lg:block">Settings</span>
        </button>
      </nav>

      <div className="p-4 border-t border-white/5 space-y-2">
        <a
          href="#"
          onClick={(e) => { e.preventDefault(); localStorage.removeItem('openshorts_skip_landing'); window.location.hash = ''; window.location.reload(); }}
          className="flex items-center gap-2 p-3 bg-white/5 hover:bg-white/10 rounded-xl transition-colors group"
        >
          <div className="w-8 h-8 rounded-full bg-primary/20 text-primary flex items-center justify-center shrink-0">
            <Globe size={16} />
          </div>
          <div className="hidden lg:block overflow-hidden">
            <p className="text-sm font-bold text-white leading-none mb-0.5">Landing Page</p>
            <p className="text-[10px] text-zinc-400 group-hover:text-zinc-300 transition-colors truncate">View website</p>
          </div>
        </a>
        <a
          href="https://github.com/mutonby/openshorts"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 p-3 bg-white/5 hover:bg-white/10 rounded-xl transition-colors group"
        >
          <div className="w-8 h-8 rounded-full bg-white text-black flex items-center justify-center shrink-0">
            <svg height="20" viewBox="0 0 16 16" version="1.1" width="20" aria-hidden="true"><path fillRule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
          </div>
          <div className="hidden lg:block overflow-hidden">
            <p className="text-sm font-bold text-white leading-none mb-0.5">Open Source</p>
            <p className="text-[10px] text-zinc-400 group-hover:text-zinc-300 transition-colors truncate">Free & Community Driven</p>
          </div>
        </a>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen bg-background overflow-hidden selection:bg-primary/30">
      <Sidebar />

      <main className="flex-1 flex flex-col h-full overflow-hidden relative">
        {/* Background Gradients */}
        <div className="absolute inset-0 overflow-hidden -z-10 pointer-events-none">
          <div className="absolute -top-[10%] -right-[10%] w-[50%] h-[50%] bg-primary/5 rounded-full blur-[120px]" />
        </div>

        {/* Top Header */}
        <header className="h-16 border-b border-white/5 bg-background/50 backdrop-blur-md flex items-center justify-between px-6 shrink-0 z-10">
          <div className="flex items-center gap-4">
            {status !== 'idle' && (
              <button
                onClick={handleReset}
                className="flex items-center gap-2 text-sm text-zinc-400 hover:text-white transition-colors"
              >
                <PlusCircle size={16} />
                <span className="hidden sm:inline">New Project</span>
              </button>
            )}
          </div>

          <div className="flex items-center gap-4">
            {userProfiles.length > 0 && (
              <UserProfileSelector
                profiles={userProfiles}
                selectedUserId={uploadUserId}
                onSelect={setUploadUserId}
              />
            )}

            {llmProvider === 'gemini' && !apiKey && (
              <span className="text-xs text-amber-500 bg-amber-500/10 px-3 py-1 rounded-full border border-amber-500/20">
                API Key Missing
              </span>
            )}
          </div>
        </header>

        {/* Main Workspace */}
        <div className="flex-1 overflow-hidden relative">

          {activeTab === 'history' && (
            <JobHistory
              jobs={historyJobs}
              loading={historyLoading}
              error={historyError}
              currentJobId={jobId}
              cancelingJobId={cancelingJobId}
              onRefresh={fetchJobHistory}
              onOpenJob={handleOpenJob}
              onResumeJob={handleResumeJob}
              onCancelJob={handleCancelJob}
            />
          )}

          {/* View: Settings */}
          {activeTab === 'settings' && (
            <div className="h-full overflow-y-auto p-8 max-w-2xl mx-auto animate-[fadeIn_0.3s_ease-out]">
              <div className="flex items-center justify-between mb-8">
                <h1 className="text-2xl font-bold">Settings</h1>
                <div className="px-3 py-1 bg-green-500/10 border border-green-500/20 rounded-full text-[10px] text-green-400 font-medium flex items-center gap-2">
                  <Shield size={12} /> Privacy: keys only live in your browser (sent to backend just to process)
                </div>
              </div>
              <div className="glass-panel p-6 mb-8">
                <label className="block text-sm text-zinc-400 mb-3">AI Provider</label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => setLlmProvider('gemini')}
                    className={`rounded-xl border px-4 py-3 text-sm text-left transition-colors ${llmProvider === 'gemini' ? 'border-primary bg-primary/10 text-white' : 'border-white/10 text-zinc-400 hover:bg-white/5'}`}
                  >
                    Gemini
                  </button>
                  <button
                    onClick={() => setLlmProvider('ollama')}
                    className={`rounded-xl border px-4 py-3 text-sm text-left transition-colors ${llmProvider === 'ollama' ? 'border-primary bg-primary/10 text-white' : 'border-white/10 text-zinc-400 hover:bg-white/5'}`}
                  >
                    Ollama
                  </button>
                </div>
              </div>
              <KeyInput
                provider={llmProvider}
                onKeySet={setApiKey}
                savedKey={apiKey}
                ollamaBaseUrl={ollamaBaseUrl}
                onOllamaBaseUrlSet={setOllamaBaseUrl}
                ollamaModel={ollamaModel}
                onOllamaModelSet={setOllamaModel}
              />

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">YouTube Download Quality</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Local setup</span>
                </div>
                <p className="text-xs text-zinc-500 leading-relaxed">
                  The downloader now aborts if YouTube only exposes a low-quality source. For locked formats, place a Netscape
                  <strong> cookies.txt</strong> in the project root or set <strong>YOUTUBE_VISITOR_DATA</strong> and optional
                  <strong> YOUTUBE_PO_TOKEN_WEB</strong>, <strong>YOUTUBE_PO_TOKEN_MWEB</strong>, <strong>YOUTUBE_PO_TOKEN_ANDROID</strong>
                  in your backend environment.
                </p>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Subtitle Defaults</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Global</span>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Font</label>
                    <select
                      value={subtitleStyle.fontFamily}
                      onChange={(e) => setSubtitleStyle((prev) => ({ ...prev, fontFamily: e.target.value }))}
                      className="input-field"
                    >
                      {FONT_OPTIONS.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Background</label>
                    <select
                      value={subtitleStyle.backgroundStyle}
                      onChange={(e) => setSubtitleStyle((prev) => ({ ...prev, backgroundStyle: e.target.value }))}
                      className="input-field"
                    >
                      {BACKGROUND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="mt-4">
                  <label className="block text-sm text-zinc-400 mb-2">Default Subtitle Y Position</label>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={subtitleStyle.yPosition ?? 86}
                    onChange={(e) => setSubtitleStyle((prev) => ({ ...prev, yPosition: Number(e.target.value) }))}
                    className="w-full accent-yellow-500"
                  />
                  <div className="mt-2 flex justify-between text-xs text-zinc-500">
                    <span>Top</span>
                    <span>{subtitleStyle.yPosition ?? 86}%</span>
                    <span>Bottom</span>
                  </div>
                </div>
                <p className="text-xs text-zinc-500 mt-4">
                  These defaults prefill the per-short subtitle dialog and can still be changed there.
                </p>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Hook Defaults</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Global</span>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Font</label>
                    <select
                      value={hookStyle.fontFamily}
                      onChange={(e) => setHookStyle((prev) => ({ ...prev, fontFamily: e.target.value }))}
                      className="input-field"
                    >
                      {FONT_OPTIONS.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Background</label>
                    <select
                      value={hookStyle.backgroundStyle}
                      onChange={(e) => setHookStyle((prev) => ({ ...prev, backgroundStyle: e.target.value }))}
                      className="input-field"
                    >
                      {BACKGROUND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <p className="text-xs text-zinc-500 mt-4">
                  These defaults prefill the per-short hook dialog and can still be overridden per clip.
                </p>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Speech Tightening</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Global</span>
                </div>
                <p className="text-xs text-zinc-500 mb-4 leading-relaxed">
                  Generated shorts can automatically cut long speech pauses and simple filler words like
                  <strong> äh</strong>, <strong> ähm</strong>, <strong> um</strong> or <strong> uh</strong>.
                  The default is intentionally aggressive for short-form pacing.
                </p>
                <label className="block text-sm text-zinc-400 mb-2">Preset</label>
                <select
                  value={tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset}
                  onChange={(e) => setTightEditSettings({ preset: e.target.value })}
                  className="input-field"
                >
                  {TIGHT_EDIT_PRESET_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <p className="text-xs text-zinc-500 mt-3">
                  {TIGHT_EDIT_PRESET_OPTIONS.find((option) => option.value === (tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset))?.description}
                </p>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Social Integration</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Optional</span>
                </div>
                <p className="text-xs text-zinc-500 mb-6 leading-relaxed">
                  Automatically publish your clips to TikTok, Instagram Reels, YouTube Shorts, Facebook, X, Threads and Pinterest via <strong>Upload-Post</strong>.
                  Includes a <strong>free tier</strong> (no credit card required).
                  If you prefer, you can skip this and manually download/upload your videos.
                </p>
                <div className="space-y-4">
                  <label className="block text-sm text-zinc-400">Upload-Post API Key</label>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={uploadPostKey}
                      onChange={(e) => setUploadPostKey(e.target.value)}
                      className="input-field"
                      placeholder="ey..."
                    />
                    <button onClick={fetchUserProfiles} className="btn-primary py-2 px-4 text-sm">
                      Connect
                    </button>
                  </div>
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Default Upload-Post Profile</label>
                    <select
                      value={uploadUserId}
                      onChange={(e) => setUploadUserId(e.target.value)}
                      className="input-field"
                      disabled={userProfiles.length === 0}
                    >
                      <option value="">{userProfiles.length === 0 ? 'Load profiles first' : 'Select profile'}</option>
                      {userProfiles.map((profile) => (
                        <option key={profile.username} value={profile.username}>{profile.username}</option>
                      ))}
                    </select>
                    <p className="text-xs text-zinc-500 mt-2">
                      This is the global Upload-Post profile used for publishing. Individual clip dialogs only show the currently active profile.
                    </p>
                  </div>
                  <div className="border border-white/5 rounded-xl p-4 space-y-4 bg-black/10">
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Default Active Platforms</label>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                        {SOCIAL_PLATFORM_OPTIONS.map((platform) => (
                          <label key={platform.key} className="flex items-center gap-2 text-sm text-zinc-300 p-2 rounded-lg border border-white/5 bg-white/5">
                            <input
                              type="checkbox"
                              checked={!!socialPostSettings.platforms[platform.key]}
                              onChange={(e) => setSocialPostSettings((prev) => ({
                                ...prev,
                                platforms: {
                                  ...prev.platforms,
                                  [platform.key]: e.target.checked,
                                },
                              }))}
                              className="w-4 h-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                            />
                            {platform.label}
                          </label>
                        ))}
                      </div>
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Default Instagram Mode</label>
                        <select
                          value={socialPostSettings.instagramShareMode}
                          onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, instagramShareMode: e.target.value }))}
                          className="input-field"
                        >
                          {INSTAGRAM_SHARE_MODES.map((mode) => (
                            <option key={mode.value} value={mode.value}>{mode.label}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Default TikTok Post Mode</label>
                        <select
                          value={socialPostSettings.tiktokPostMode}
                          onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, tiktokPostMode: e.target.value }))}
                          className="input-field"
                        >
                          {TIKTOK_POST_MODES.map((mode) => (
                            <option key={mode.value} value={mode.value}>{mode.label}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <label className="flex items-center gap-3 text-sm text-zinc-300">
                      <input
                        type="checkbox"
                        checked={!!socialPostSettings.tiktokIsAigc}
                        onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, tiktokIsAigc: e.target.checked }))}
                        className="w-4 h-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                      />
                      Mark TikTok uploads as AI-generated by default
                    </label>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Default Facebook Page ID</label>
                        <input
                          type="text"
                          value={socialPostSettings.facebookPageId}
                          onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, facebookPageId: e.target.value }))}
                          className="input-field"
                          placeholder="Optional"
                        />
                      </div>
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Default Pinterest Board ID</label>
                        <input
                          type="text"
                          value={socialPostSettings.pinterestBoardId}
                          onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, pinterestBoardId: e.target.value }))}
                          className="input-field"
                          placeholder="Required for Pinterest posts"
                        />
                      </div>
                    </div>
                    <p className="text-xs text-zinc-500 leading-relaxed">
                      The detected transcript language is forwarded where Upload-Post currently supports language fields. In the current upload docs that is YouTube, not TikTok.
                    </p>
                  </div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Connect your Upload-Post account to enable one-click publishing.
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2">
                      <a href="https://app.upload-post.com/login" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">1. Login</span>
                        <span className="text-[10px] text-zinc-600">Register account</span>
                      </a>
                      <a href="https://app.upload-post.com/manage-users" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">2. Profiles</span>
                        <span className="text-[10px] text-zinc-600">Create & Connect</span>
                      </a>
                      <a href="https://app.upload-post.com/api-keys" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">3. API Key</span>
                        <span className="text-[10px] text-zinc-600">Generate key</span>
                      </a>
                    </div>
                    <br />
                    <span className="text-zinc-600 italic">
                      Keys are only stored in your browser. They are sent to the backend only to process your request, never stored server-side.
                    </span>
                  </p>
                </div>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Video Translation</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Optional</span>
                </div>
                <p className="text-xs text-zinc-500 mb-6 leading-relaxed">
                  Translate your clips to different languages using <strong>ElevenLabs</strong> AI dubbing.
                  Automatically translates speech while preserving the original voice characteristics.
                </p>
                <div className="space-y-4">
                  <label className="block text-sm text-zinc-400">ElevenLabs API Key</label>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={elevenLabsKey}
                      onChange={(e) => setElevenLabsKey(e.target.value)}
                      className="input-field"
                      placeholder="sk_..."
                    />
                    <button
                      onClick={() => {
                        if (elevenLabsKey) {
                          localStorage.setItem('elevenLabsKey_v1', encrypt(elevenLabsKey));
                          alert('ElevenLabs API Key saved!');
                        }
                      }}
                      className="btn-primary py-2 px-4 text-sm"
                    >
                      Save
                    </button>
                  </div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Get your API key from ElevenLabs to enable video translation.
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <a href="https://elevenlabs.io/sign-up" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">1. Sign Up</span>
                        <span className="text-[10px] text-zinc-600">Create account</span>
                      </a>
                      <a href="https://elevenlabs.io/app/settings/api-keys" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">2. API Key</span>
                        <span className="text-[10px] text-zinc-600">Generate key</span>
                      </a>
                    </div>
                    <br />
                    <span className="text-zinc-600 italic">
                      Keys are only stored in your browser. They are sent to the backend only to process your request, never stored server-side.
                    </span>
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* View: Thumbnails */}
          {activeTab === 'thumbnails' && (
            <ThumbnailStudio geminiApiKey={apiKey} uploadPostKey={uploadPostKey} uploadUserId={uploadUserId} />
          )}

          {/* View: Gallery */}
          {/* {activeTab === 'gallery' && (
            <Gallery />
          )} */}

          {/* View: Dashboard (Idle) */}
          {activeTab === 'dashboard' && status === 'idle' && (
            <div className="h-full flex flex-col items-center justify-center p-6 animate-[fadeIn_0.3s_ease-out]">
              <div className="max-w-xl w-full text-center space-y-8">
                <div className="space-y-4">
                  <h1 className="text-4xl md:text-5xl font-black bg-gradient-to-b from-white to-white/60 bg-clip-text text-transparent">
                    Create Viral Shorts
                  </h1>
                  <p className="text-zinc-400 text-lg">
                    Drop your long-form video URL or file below to instantly generate viral clips with AI.
                  </p>
                </div>

                <MediaInput onProcess={handleProcess} isProcessing={status === 'processing'} />

                <div className="flex items-center justify-center gap-8 text-zinc-500 text-sm">
                  <span className="flex items-center gap-2"><Youtube size={16} /> YouTube</span>
                  <span className="flex items-center gap-2"><Instagram size={16} /> Instagram</span>
                  <span className="flex items-center gap-2"><TikTokIcon size={16} /> TikTok</span>
                </div>
              </div>
            </div>
          )}

          {/* View: Processing / Results (Split View) */}
          {activeTab === 'dashboard' && (status === 'processing' || status === 'complete' || status === 'error') && (
            <div className="h-full flex flex-col md:flex-row animate-[fadeIn_0.3s_ease-out]">

              {/* Left Panel: Preview & Status */}
              <div className={`${status === 'complete' ? 'w-full md:w-[30%] lg:w-[25%]' : 'w-full md:w-[55%] lg:w-[60%]'} h-full flex flex-col border-r border-white/5 bg-black/20 p-6 overflow-y-auto custom-scrollbar transition-all duration-700 ease-in-out`}>
                <div className="mb-6 flex items-center justify-between">
                  <h2 className="text-lg font-semibold flex items-center gap-2">
                    <Activity className={`text-primary ${status === 'processing' ? 'animate-pulse' : ''}`} size={20} />
                    Live Analysis
                  </h2>
                  <span className={`text-xs px-2 py-1 rounded-full border ${status === 'processing' ? 'bg-primary/10 border-primary/20 text-primary' :
                    status === 'complete' ? 'bg-green-500/10 border-green-500/20 text-green-400' :
                      'bg-red-500/10 border-red-500/20 text-red-400'
                    }`}>
                    {(status === 'processing'
                      ? jobState
                      : (status === 'complete' && jobState === 'partial') || (status === 'error' && jobState === 'cancelled')
                        ? jobState
                        : status
                    ).toUpperCase()}
                  </span>
                </div>

                {/* Video Preview */}
                {processingMedia && (
                  <ProcessingAnimation
                    media={processingMedia}
                    isComplete={status === 'complete'}
                    syncedTime={syncedTime}
                    isSyncedPlaying={isSyncedPlaying}
                    syncTrigger={syncTrigger}
                  />
                )}

                {/* Logs Terminal */}
                <div className={`bg-[#0c0c0e] rounded-xl border border-white/10 overflow-hidden flex flex-col transition-all duration-500 ${status === 'complete' ? 'h-32 min-h-0 opacity-50 hover:opacity-100' : 'flex-1 min-h-[200px]'}`}>
                  <div className="px-4 py-2 border-b border-white/5 flex items-center justify-between bg-white/5 shrink-0">
                    <span className="text-xs font-mono text-zinc-400 flex items-center gap-2">
                      <Terminal size={12} /> System Logs
                    </span>
                    <button onClick={() => setLogsVisible(!logsVisible)} className="text-zinc-500 hover:text-white transition-colors">
                      {logsVisible ? <ChevronDown size={14} /> : <ChevronDown size={14} className="rotate-180" />}
                    </button>
                  </div>
                  {logsVisible && (
                    <div className="flex-1 p-4 overflow-y-auto font-mono text-xs space-y-1.5 custom-scrollbar text-zinc-400">
                      {logs.map((log, i) => (
                        <div key={i} className={`flex gap-2 ${log.toLowerCase().includes('error') ? 'text-red-400' : 'text-zinc-400'}`}>
                          <span className="text-zinc-700 shrink-0">{new Date().toLocaleTimeString()}</span>
                          <span>{log}</span>
                        </div>
                      ))}
                      {status === 'processing' && (
                        <div className="animate-pulse text-primary/70">_</div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Right Panel: Results Grid */}
              <div className={`${status === 'complete' ? 'w-full md:w-[70%] lg:w-[75%]' : 'w-full md:w-[45%] lg:w-[40%]'} h-full flex flex-col bg-background p-6 transition-all duration-700 ease-in-out`}>
                <h2 className="text-lg font-semibold mb-6 flex items-center gap-2 shrink-0">
                  <Sparkles className="text-yellow-400" size={20} />
                  Generated Shorts
                  {results?.clips?.length > 0 && (
                    <span className="text-xs bg-white/10 text-white px-2 py-0.5 rounded-full ml-auto">
                      {results.clips.length} Clips
                    </span>
                  )}
                  {results?.cost_analysis && (
                    <span className="text-xs bg-green-500/10 border border-green-500/20 text-green-400 px-2 py-0.5 rounded-full ml-2" title={`Input: ${results.cost_analysis.input_tokens} | Output: ${results.cost_analysis.output_tokens}`}>
                      ${results.cost_analysis.total_cost.toFixed(5)}
                    </span>
                  )}
                </h2>

                <div className="flex-1 overflow-y-auto custom-scrollbar p-1">
                  {results && results.clips && results.clips.length > 0 ? (
                    <div className={`grid gap-4 pb-10 ${status === 'complete' ? 'grid-cols-1 xl:grid-cols-2' : 'grid-cols-1'}`}>
                      {results.clips.map((clip, i) => (
                        <ResultCard
                          key={`${jobId || 'job'}:${clip.clip_index ?? i}`}
                          clip={clip}
                          index={i}
                          jobId={jobId}
                          uploadPostKey={uploadPostKey}
                          uploadUserId={uploadUserId}
                          geminiApiKey={apiKey}
                          llmProvider={llmProvider}
                          ollamaBaseUrl={ollamaBaseUrl}
                          ollamaModel={ollamaModel}
                          elevenLabsKey={elevenLabsKey}
                          subtitleStyle={subtitleStyle}
                          hookStyle={hookStyle}
                          socialPostSettings={socialPostSettings}
                          activeUploadProfile={uploadUserId}
                          currentVideoOverride={clipVideoOverrides[getClipVariantKey(jobId, clip, i)]}
                          onVideoVariantChange={(videoUrl) => updateClipVideoOverride(jobId, clip, i, videoUrl)}
                          onClipUpdated={(updatedClip) => updateClipResult(jobId, updatedClip)}
                          onPlay={(time) => handleClipPlay(time)}
                          onPause={handleClipPause}
                        />
                      ))}
                    </div>
                  ) : (
                    status === 'processing' ? (
                      <div className="h-full flex flex-col items-center justify-center text-zinc-500 space-y-4 opacity-50">
                        <div className="w-12 h-12 rounded-full border-2 border-zinc-800 border-t-primary animate-spin" />
                        <p className="text-sm">Waiting for clips...</p>
                      </div>
                    ) : status === 'error' ? (
                      <div className="h-full flex flex-col items-center justify-center text-red-400 space-y-2">
                        <p>Generation failed.</p>
                      </div>
                    ) : null
                  )}
                </div>
              </div>

            </div>
          )}

        </div>
      </main>
    </div>
  );
}

export default App;
