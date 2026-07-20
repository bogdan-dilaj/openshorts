import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Upload, Download, FileVideo, Sparkles, Youtube, Instagram, Share2, LogOut, ChevronDown, Check, Activity, LayoutDashboard, Settings, PlusCircle, History, Menu, X, Terminal, Shield, LayoutGrid, Image, Globe, Loader2, CalendarDays, Clock3, ListFilter, GripVertical, SkipForward, AudioLines, RefreshCcw, RotateCcw } from 'lucide-react';
import MediaInput from './components/MediaInput';
import ResultCard from './components/ResultCard';
import ProcessingAnimation from './components/ProcessingAnimation';
// import Gallery from './components/Gallery';
import ThumbnailStudio from './components/ThumbnailStudio';
import JobHistory from './components/JobHistory';
import SocialUploadStudio from './components/SocialUploadStudio';
import LongformVideoEditor from './components/LongformVideoEditor';
import TranscriptionStudio from './components/TranscriptionStudio';
import UploadPostCalendarModal from './components/UploadPostCalendarModal';
import { getApiUrl } from './config';
import { BACKGROUND_OPTIONS, DEFAULT_HOOK_STYLE, DEFAULT_SUBTITLE_STYLE, FONT_OPTIONS, GRID_OPTIONS, HOOK_WIDTH_OPTIONS, PATTERN_FLASH_MODE_OPTIONS } from './overlayOptions';
import { DEFAULT_SOCIAL_POST_SETTINGS, INSTAGRAM_SHARE_MODES, SOCIAL_PLATFORM_OPTIONS, TIKTOK_POST_MODES } from './socialOptions';

// Enhanced "Encryption" using XOR + Base64 with a Salt
// This is better than plain Base64 but still client-side.
const SECRET_KEY = import.meta.env.VITE_ENCRYPTION_KEY || "OpenShorts-Static-Salt-Change-Me";
const ENCRYPTION_PREFIX = "ENC:";
const SETTINGS_EXPORT_FORMAT = 'openshorts-settings';
const SETTINGS_EXPORT_VERSION = 1;
const SETTINGS_EXPORT_MAX_BYTES = 2 * 1024 * 1024;

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

const BULK_OPERATION_MODES = {
  RENDER_AND_POST: 'render+post',
  RENDER_ONLY: 'render-only',
  POST_ONLY: 'post-only',
};

const BULK_OPERATION_CONFIG = {
  [BULK_OPERATION_MODES.RENDER_AND_POST]: {
    requiresRender: true,
    requiresPost: true,
    label: 'Rendern & planen',
    successLabel: 'gerendert und fuer die naechsten Slots eingeplant',
    progressButtonLabel: 'Bearbeite Auswahl...',
  },
  [BULK_OPERATION_MODES.RENDER_ONLY]: {
    requiresRender: true,
    requiresPost: false,
    label: 'Nur rendern',
    successLabel: 'gerendert',
    progressButtonLabel: 'Rendere Auswahl...',
  },
  [BULK_OPERATION_MODES.POST_ONLY]: {
    requiresRender: false,
    requiresPost: true,
    label: 'Nur planen',
    successLabel: 'fuer die naechsten Slots eingeplant',
    progressButtonLabel: 'Plane Auswahl...',
  },
};

const DEFAULT_NANO_BANANA_THUMBNAIL_PROMPT = `{
  "task": {
    "objective": "photo-based composite thumbnail generation",
    "aspect_ratio": "16:9",
    "style": "high-end professional real-photo YouTube thumbnail"
  },
  "content_preservation": {
    "source_references": [
      "Image 1 (Left Person)",
      "Image 2 (Right Person)"
    ],
    "constraints": {
      "faces": {
        "priority": "highest",
        "action": "maintain 1:1 near-identical fidelity to original images",
        "prohibitions": [
          "do not change facial structure",
          "do not change proportions",
          "do not change skin texture",
          "do not change hairline",
          "do not change eyes, nose, mouth, jawline",
          "do not change identity",
          "do not change facial expressions",
          "do not mimic or reinterpret",
          "do not beautify",
          "do not stylize",
          "do not reconstruct",
          "maintain natural imperfections and asymmetry"
        ]
      },
      "geometry": {
        "prohibitions": [
          "do not regenerate faces",
          "do not change facial geometry",
          "do not change expression",
          "do not change head angle",
          "do not change pose",
          "do not smooth skin",
          "do not apply beauty retouching",
          "do not relight faces in a way that changes structure"
        ]
      }
    }
  },
  "technical_enhancements": {
    "allowed_actions": [
      "precise background removal with high-detail hair masking",
      "refined cut-out edges",
      "cinematic contrast and color grading",
      "global brightness and contrast correction optimized for facial clarity",
      "white balance correction",
      "targeted enhancement of existing mood while preserving realistic depth",
      "advanced facial sharpening for extreme detail",
      "color correction for cinematic consistency on faces",
      "enhance existing mood while preserving realistic depth"
      "subtle glare reduction on the forehead if applicable",
      "enhance eye details and catchlights with natural clarity",
      "color balancing"
    ]
  },
  "lighting": {
    "style": "high-contrast cinematic and perfectly illuminated faces",
    "characteristics": [
      "strong facial clarity as the top visual priority",
      "soft, sophisticated micro-shadows for depth",
      "precise, clear catchlights in the eyes",
      "optimized facial visibility, ensuring no facial details are lost in shadow or look flat"
    ]
  },
  "composition": {
    "layout": "split-host portrait",
    "focal_point": "strong visual focus on faces",
    "framing": {
      "type": "face close-up portrait"
    },
    "positioning": {
      "person_1": {
        "source": "Image 1",
        "placement": "left"
      },
      "person_2": {
        "source": "Image 2",
        "placement": "right"
      }
    },
    "background": {
      "type": "smooth #2d92f7 gradient",
      "style": "clean, minimalist, modern premium podcast/interview aesthetic",
      "vignette": "subtle, toward the edges",
      "prohibitions": [
        "no visible studio elements",
        "no distracting textures"
      ]
    }
  },
  "typography": {
    "headline": {
      "content": "<text_overlay>",
      "placement": "center, between the two subjects",
      "layout": "compact rectangular text block",
      "lines": "2 to 4 balanced lines based on length",
      "line_breaks": "avoid awkward or single-word lines",
      "hierarchy": {
        "dominant_line": {
          "criteria": "most important keyword/phrase",
          "size": "100%"
        },
        "supporting_lines": {
          "size": "60-85%"
        }
      },
      "font": {
        "style": "bold condensed sans-serif (similar to Impact/Anton/Bebas Neue)",
        "color": "white",
        "readability": "subtle dark shadow or soft outline",
        "spacing": "tight line spacing, slightly condensed letter spacing",
        "prohibitions": [
          "no gradients",
          "no glossy effects",
          "no flashy colors"
        ]
      },
      "underline": {
        "type": "minimal, organic, subtle hand-drawn/brush-style",
        "color": "white or off-white",
        "placement": "under the dominant final line or key emphasis line ONLY"
      }
    }
  },
  "lighting": {
    "style": "high-contrast cinematic",
    "characteristics": [
      "strong facial clarity",
      "soft shadows for depth"
    ]
  },
  "negative_prompt": {
    "exclusions": [
      "different person",
      "altered identity",
      "changed face",
      "changed expression",
      "face reconstruction",
      "stylized face",
      "cartoon",
      "painting",
      "unrealistic skin",
      "over-smoothed skin",
      "beauty retouching",
      "face swap",
      "AI-generated face look",
      "changed head angle",
      "altered proportions",
      "synthetic portrait",
      "face symmetry and pose change not naturally supported by input"
    ]
  }
}`;

const DEFAULT_LONGFORM_THUMBNAIL_PROMPTS = [
  {
    id: 'nano_banana_split_host',
    name: 'Nano Banana Split Host',
    prompt: DEFAULT_NANO_BANANA_THUMBNAIL_PROMPT,
  },
  {
    id: 'clean_editorial',
    name: 'Clean Editorial',
    prompt: 'Erzeuge ein professionelles, modernes YouTube-Thumbnails fuer ein Gespraechsformat. Nutze die Referenzbilder als inhaltliche Basis, aber halte das Layout sauber, glaubwuerdig und hochwertig. Wenig Text, starke Blickrichtung, klare Motivtrennung, praegnante Lichtsetzung und journalistischer Look.',
  },
];

const DEFAULT_LONGFORM_THUMBNAIL_MODEL_DEFAULTS = {
  gemini: 'gemini-3.1-flash-image',
  openai: 'gpt-image-1',
  midjourney: 'auto',
};

const MINIMAX_AUTH_MODE_OPTIONS = [
  {
    value: 'token_plan',
    label: 'Token Plan',
    description: 'Verwendet den separaten Token-Plan-Key aus deinem MiniMax-Token-Plan. Nicht mit Pay-as-you-go austauschbar.',
  },
  {
    value: 'payg',
    label: 'Pay-as-you-go',
    description: 'Verwendet den normalen Open-Platform-API-Key fuer verbrauchsbasierte Abrechnung.',
  },
];

const DEFAULT_LONGFORM_AI_DEFAULTS = {
  provider: 'ollama',
  ollama_base_url: 'http://127.0.0.1:11434',
  ollama_model: 'gemma3:12b',
};

const normalizeLongformAiDefaults = (value) => {
  const source = value && typeof value === 'object' ? value : {};
  const provider = String(source.provider || DEFAULT_LONGFORM_AI_DEFAULTS.provider).trim().toLowerCase();
  return {
    provider: ['off', 'ollama', 'gemini', 'openai', 'claude', 'minimax'].includes(provider)
      ? provider
      : DEFAULT_LONGFORM_AI_DEFAULTS.provider,
    ollama_base_url: String(source.ollama_base_url || DEFAULT_LONGFORM_AI_DEFAULTS.ollama_base_url).trim() || DEFAULT_LONGFORM_AI_DEFAULTS.ollama_base_url,
    ollama_model: String(source.ollama_model || DEFAULT_LONGFORM_AI_DEFAULTS.ollama_model).trim() || DEFAULT_LONGFORM_AI_DEFAULTS.ollama_model,
  };
};

const THUMBNAIL_MODEL_SUGGESTIONS = {
  gemini: ['gemini-3.1-flash-image', 'gemini-3.1-flash-image-preview', 'gemini-3-pro-image-preview', 'gemini-2.5-flash-image', 'auto'],
  openai: ['gpt-image-1'],
  midjourney: ['auto', 'v7', 'v6.1', 'niji 6'],
};

const normalizeLongformThumbnailPromptPresets = (value) => {
  const source = Array.isArray(value) ? value : [];
  const normalized = source
    .map((item, index) => ({
      id: String(item?.id || item?.name || `preset_${index + 1}`).trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_'),
      name: String(item?.name || `Preset ${index + 1}`).trim(),
      prompt: String(item?.prompt || '').trim(),
    }))
    .filter((item) => item.name && item.prompt);
  return normalized.length ? normalized : DEFAULT_LONGFORM_THUMBNAIL_PROMPTS;
};

const normalizeLongformThumbnailModelDefaults = (value) => {
  const source = value && typeof value === 'object' ? value : {};
  const normalizeGeminiModel = (model) => {
    const normalized = String(model || '').trim();
    if (!normalized) return DEFAULT_LONGFORM_THUMBNAIL_MODEL_DEFAULTS.gemini;
    if (normalized === 'gemini-2.5-flash') {
      return 'gemini-2.5-flash-image';
    }
    if (normalized === 'gemini-3.1-flash-image') {
      return 'gemini-3.1-flash-image-preview';
    }
    if (['gemini-3.1-flash-image-preview', 'gemini-3-pro-image-preview', 'gemini-2.5-flash-image'].includes(normalized)) {
      return normalized;
    }
    return normalized;
  };
  return {
    gemini: normalizeGeminiModel(source.gemini || DEFAULT_LONGFORM_THUMBNAIL_MODEL_DEFAULTS.gemini),
    openai: String(source.openai || DEFAULT_LONGFORM_THUMBNAIL_MODEL_DEFAULTS.openai).trim() || DEFAULT_LONGFORM_THUMBNAIL_MODEL_DEFAULTS.openai,
    midjourney: String(source.midjourney || DEFAULT_LONGFORM_THUMBNAIL_MODEL_DEFAULTS.midjourney).trim() || DEFAULT_LONGFORM_THUMBNAIL_MODEL_DEFAULTS.midjourney,
  };
};

const inferClipVersionOperation = (filename) => {
  const normalized = String(filename || '').trim().toLowerCase();
  if (!normalized) return 'original';
  if (normalized.startsWith('viral_rendered_')) return 'viral_render';
  if (normalized.startsWith('rendered_')) return 'render';
  if (normalized.startsWith('subtitled_')) return 'subtitle';
  if (normalized.startsWith('hook_')) return 'hook';
  if (normalized.startsWith('edited_')) return 'edit';
  if (normalized.startsWith('translated_')) return 'translate';
  if (normalized.startsWith('trimmed_')) return 'trim';
  return 'original';
};

const resolveActiveClipVersion = (clip) => {
  const versions = Array.isArray(clip?.versions) ? clip.versions : [];
  if (versions.length) {
    return versions.find((item) => item.id === clip?.active_version_id) || versions[versions.length - 1];
  }
  const filename = clip?.video_filename || clip?.video_url?.split('/').pop() || '';
  if (!filename) return null;
  return {
    filename,
    operation: inferClipVersionOperation(filename),
  };
};

const isClipReadyForBulkScheduling = (clip) => {
  const activeVersion = resolveActiveClipVersion(clip);
  return !!activeVersion && activeVersion.operation !== 'original';
};

const isClipRendered = (clip) => {
  return Boolean(clip?.video_url) || String(clip?.status || '').trim().toLowerCase() === 'completed';
};

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
          <span className="font-medium text-white truncate max-w-[100px]">{selectedProfile?.username || "Profil wählen"}</span>
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
  if (!res.ok) throw new Error('Statusprüfung fehlgeschlagen');
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

const fetchWithTimeout = async (url, options = {}, timeoutMs = 15000) => {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
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

const DEFAULT_PODCAST_DM_SETTINGS = {
  relayUrl: '',
  relayPassword: '',
  defaultKeyword: 'Video',
};

const readStoredPodcastDmSettings = () => {
  try {
    const raw = localStorage.getItem('podcast_dm_settings_v1');
    if (!raw) return DEFAULT_PODCAST_DM_SETTINGS;
    const parsed = JSON.parse(raw);
    return {
      ...DEFAULT_PODCAST_DM_SETTINGS,
      ...parsed,
      relayPassword: decrypt(parsed.relayPassword || ''),
    };
  } catch (e) {
    return DEFAULT_PODCAST_DM_SETTINGS;
  }
};

const JOB_SHORTS_UI_STATE_PREFIX = 'job_shorts_ui_v1:';

const buildJobUiStorageKey = (jobId) => `${JOB_SHORTS_UI_STATE_PREFIX}${jobId}`;

const readStoredJobUiState = (jobId) => {
  if (!jobId) return null;
  try {
    const raw = localStorage.getItem(buildJobUiStorageKey(jobId));
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
};

const writeStoredJobUiState = (jobId, state) => {
  if (!jobId) return;
  try {
    localStorage.setItem(buildJobUiStorageKey(jobId), JSON.stringify(state));
  } catch (e) {
    console.warn('Failed to persist job UI state', e);
  }
};

const BULK_RUNNING_STATUSES = new Set(['running', 'pause_requested', 'stop_requested']);
const BULK_RESUMABLE_STATUSES = new Set(['paused', 'partial', 'failed']);
const GLOBAL_SCHEDULE_BATCH_STORAGE_KEY = 'global_schedule_batch_v1';
const DEFAULT_PODCAST_COMMENT_TEMPLATE = 'Kommentiere "<keyword>" und wir senden dir den Link zum Podcast zu';

const renderPodcastCommentTemplate = (template, keyword) => String(template || DEFAULT_PODCAST_COMMENT_TEMPLATE)
  .replace(/<keyword>/gi, String(keyword || 'Video').trim() || 'Video');

const isBulkOperationRunning = (operation) => BULK_RUNNING_STATUSES.has(String(operation?.status || '').toLowerCase());
const isBulkOperationResumable = (operation) => BULK_RESUMABLE_STATUSES.has(String(operation?.status || '').toLowerCase());

const formatBulkOperationSummary = (operation) => {
  if (!operation) return '';
  const completed = Number(operation.completed_count || 0);
  const rendered = Number(operation.render_completed_count || 0);
  const posted = Number(operation.post_completed_count || 0);
  const total = Number(operation.total_count || 0);
  const phase = String(operation.current_phase || '').toLowerCase();
  const base = operation.message || '';
  if (phase === 'render') return `${rendered}/${total} gerendert · Rendering`;
  if (phase === 'post') return `${posted}/${total} gepostet/eingeplant · Posting`;
  if (base) return `${completed}/${total} fertig · ${base}`;
  return `${completed}/${total} fertig`;
};

const formatDateInputValue = (date = new Date()) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const resolveClipDurationSeconds = (clip) => {
  const numeric = Number(clip?.display_duration);
  if (Number.isFinite(numeric)) return numeric;
  return Math.max(0, Number(clip?.end || 0) - Number(clip?.start || 0));
};

const resolveClipHookDraftText = (clip) => (
  String(clip?.hook_settings?.text || clip?.viral_hook_text || '').trim()
);

const buildClipSelectionKey = (activeJobId, clip, fallbackIndex) => {
  const revision = String(clip?.analysis_revision || 'legacy');
  return `${activeJobId}:${revision}:${clip?.clip_index ?? fallbackIndex}`;
};

const isClipPostedOrQueued = (clip) => {
  const status = clip?.social_post_status;
  if (!status || typeof status !== 'object') return false;

  const normalizedStatus = String(status.status || '').toLowerCase();
  const pendingCount = Number(status.pending_count || 0);
  const successCount = Number(status.success_count || 0);

  return (
    pendingCount > 0
    || successCount > 0
    || ['pending', 'in_progress', 'scheduled', 'upcoming', 'completed', 'partial'].includes(normalizedStatus)
  );
};

const isClipPostFailed = (clip) => {
  const status = clip?.social_post_status;
  if (!status || typeof status !== 'object') return false;
  const normalizedStatus = String(status.status || '').toLowerCase();
  const failureCount = Number(status.failure_count || 0);
  if (normalizedStatus === 'upcoming') return false;
  return failureCount > 0 || ['failed', 'partial', 'error'].includes(normalizedStatus);
};

const moveArrayItem = (items, fromIndex, toIndex) => {
  if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return items;
  const next = [...items];
  const [moved] = next.splice(fromIndex, 1);
  if (moved === undefined) return items;
  next.splice(toIndex, 0, moved);
  return next;
};

const parseDailyScheduleSlots = (value, { preserveOrder = false } = {}) => {
  const entries = String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

  if (!entries.length) {
    throw new Error('Mindestens einen Posting-Slot angeben, z. B. 12:00, 15:00, 18:00.');
  }

  const seen = new Set();
  const slots = entries.map((entry) => {
    const match = entry.match(/^(\d{1,2})(?::(\d{2}))?$/);
    if (!match) {
      throw new Error(`Ungueltiger Slot "${entry}". Erlaubt ist HH:MM.`);
    }
    const hours = Number(match[1]);
    const minutes = Number(match[2] || '00');
    if (!Number.isInteger(hours) || hours < 0 || hours > 23 || !Number.isInteger(minutes) || minutes < 0 || minutes > 59) {
      throw new Error(`Ungueltiger Slot "${entry}". Stunden 0-23, Minuten 0-59.`);
    }
    return {
      hours,
      minutes,
      label: `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`,
      inputOrder: entries.indexOf(entry),
      sortKey: hours * 60 + minutes,
    };
  });

  if (!preserveOrder) {
    slots.sort((a, b) => a.sortKey - b.sortKey);
  }

  return slots.filter((slot) => {
    if (seen.has(slot.label)) return false;
    seen.add(slot.label);
    return true;
  });
};

const buildScheduledPostDates = ({
  slotText,
  count,
  startDate,
  dayInterval = 1,
  staggerSlotsByDay = false,
  slotOffset = 0,
}) => {
  const slots = parseDailyScheduleSlots(slotText, { preserveOrder: staggerSlotsByDay });
  const baseDate = new Date(`${startDate || formatDateInputValue()}T00:00:00`);
  if (Number.isNaN(baseDate.getTime())) {
    throw new Error('Ungueltiges Startdatum.');
  }
  const normalizedDayInterval = Math.max(1, Number(dayInterval) || 1);
  const normalizedSlotOffset = Math.max(0, Number(slotOffset) || 0);

  const now = new Date();
  const scheduledDates = [];

  if (normalizedSlotOffset > 0) {
    for (let scheduleIndex = normalizedSlotOffset; scheduleIndex < normalizedSlotOffset + count; scheduleIndex += 1) {
      let candidate;
      if (staggerSlotsByDay) {
        const slot = slots[scheduleIndex % slots.length];
        candidate = new Date(baseDate);
        candidate.setDate(baseDate.getDate() + (scheduleIndex * normalizedDayInterval));
        candidate.setHours(slot.hours, slot.minutes, 0, 0);
      } else {
        const slot = slots[scheduleIndex % slots.length];
        const dayOffset = Math.floor(scheduleIndex / slots.length) * normalizedDayInterval;
        candidate = new Date(baseDate);
        candidate.setDate(baseDate.getDate() + dayOffset);
        candidate.setHours(slot.hours, slot.minutes, 0, 0);
      }
      scheduledDates.push(candidate);
    }

    if (scheduledDates.some((candidate) => candidate <= now)) {
      throw new Error('Skip + Startdatum verweisen auf vergangene Slots. Bitte Startdatum anpassen oder Skip verringern.');
    }

    return scheduledDates;
  }

  if (staggerSlotsByDay) {
    const firstSlot = slots[0];
    const firstCandidate = new Date(baseDate);
    firstCandidate.setHours(firstSlot.hours, firstSlot.minutes, 0, 0);

    let safetyCounter = 0;
    const safetyLimit = Math.max(count * slots.length * normalizedDayInterval * 4, 128);
    while (firstCandidate <= now && safetyCounter < safetyLimit) {
      firstCandidate.setDate(firstCandidate.getDate() + normalizedDayInterval);
      safetyCounter += 1;
    }

    if (firstCandidate <= now) {
      throw new Error('Es konnten nicht genug zukuenftige gestaffelte Posting-Slots erzeugt werden.');
    }

    for (let scheduleIndex = 0; scheduleIndex < count; scheduleIndex += 1) {
      const slot = slots[scheduleIndex % slots.length];
      const candidate = new Date(firstCandidate);
      candidate.setDate(firstCandidate.getDate() + (scheduleIndex * normalizedDayInterval));
      candidate.setHours(slot.hours, slot.minutes, 0, 0);
      scheduledDates.push(candidate);
    }

    return scheduledDates;
  }

  let cycleIndex = 0;
  const safetyLimit = Math.max(count * normalizedDayInterval * 4, normalizedDayInterval * 24, 32);

  while (scheduledDates.length < count && cycleIndex < safetyLimit) {
    const dayOffset = cycleIndex * normalizedDayInterval;
    const day = new Date(baseDate);
    day.setHours(0, 0, 0, 0);
    day.setDate(baseDate.getDate() + dayOffset);

    for (const slot of slots) {
      const candidate = new Date(day);
      candidate.setHours(slot.hours, slot.minutes, 0, 0);
      if (candidate <= now) continue;
      scheduledDates.push(candidate);
      if (scheduledDates.length >= count) break;
    }

    cycleIndex += 1;
  }

  if (scheduledDates.length < count) {
    throw new Error('Es konnten nicht genug zukuenftige Posting-Slots erzeugt werden.');
  }

  return scheduledDates;
};

const formatSchedulePreviewLabel = (value) => new Intl.DateTimeFormat('de-DE', {
  weekday: 'short',
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
}).format(value);

const buildSubtitleSettingsPayload = (style) => {
  const normalized = normalizeSubtitleStyleConfig(style || DEFAULT_SUBTITLE_STYLE);
  return {
    position: normalized.position,
    y_position: normalized.yPosition,
    font_size: normalized.fontSize,
    font_family: normalized.fontFamily,
    background_style: normalized.backgroundStyle,
  };
};

const buildHookSettingsPayload = (style, hookText) => {
  const normalized = normalizeHookStyleConfig(style || DEFAULT_HOOK_STYLE);
  return {
    text: hookText,
    position: normalized.position,
    horizontal_position: normalized.horizontalPosition,
    x_position: normalized.xPosition,
    y_position: normalized.yPosition,
    text_align: normalized.textAlign,
    size: normalized.size,
    width_preset: normalized.widthPreset,
    font_family: normalized.fontFamily,
    background_style: normalized.backgroundStyle,
    start_zoom_factor: normalized.startZoomFactor,
    zoom_factor: normalized.zoomFactor,
    flash_mode: normalized.flashMode,
  };
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

const SHORTFORM_PROVIDER_OPTIONS = [
  { value: 'gemini', label: 'Gemini' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'minimax', label: 'MiniMax' },
  { value: 'claude', label: 'Claude' },
  { value: 'ollama', label: 'Ollama' },
];

const DEFAULT_SHORTFORM_MODELS = {
  gemini: 'gemini-2.5-flash',
  openai: 'gpt-4.1-mini',
  minimax: 'MiniMax-M3',
  claude: 'claude-3-5-sonnet-latest',
  ollama: 'llama3.1:8b',
};

const SHORTFORM_MODEL_SUGGESTIONS = {
  gemini: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-1.5-pro'],
  openai: ['gpt-4.1-mini', 'gpt-4.1', 'gpt-4o-mini'],
  minimax: ['MiniMax-M3', 'MiniMax-M2.7', 'MiniMax-M2.7-highspeed', 'MiniMax-M2.5-highspeed', 'MiniMax-M2.5', 'MiniMax-M2.1-highspeed', 'MiniMax-M2.1', 'MiniMax-M2'],
  claude: ['claude-3-5-sonnet-latest', 'claude-3-7-sonnet-latest'],
  ollama: ['llama3.1:8b', 'gemma3:12b', 'qwen2.5:14b'],
};

const normalizeShortformProvider = (value) => {
  const normalized = String(value || '').trim().toLowerCase();
  return SHORTFORM_PROVIDER_OPTIONS.some((option) => option.value === normalized) ? normalized : 'gemini';
};

const normalizeShortformModel = (provider, value) => {
  const normalizedProvider = normalizeShortformProvider(provider);
  const trimmed = String(value || '').trim();
  if (!trimmed) {
    return DEFAULT_SHORTFORM_MODELS[normalizedProvider] || DEFAULT_SHORTFORM_MODELS.gemini;
  }
  if (normalizedProvider === 'minimax') {
    const aliasMap = {
      'minimax-text-01': 'MiniMax-M3',
      'minimax-m1': 'MiniMax-M3',
      'minimax-m2': 'MiniMax-M3',
      'minimax-m2.1': 'MiniMax-M3',
      'minimax-m2.1-highspeed': 'MiniMax-M3',
      'minimax-m2.5': 'MiniMax-M3',
      'minimax-m2.5-highspeed': 'MiniMax-M3',
      'minimax-m3': 'MiniMax-M3',
    };
    return aliasMap[trimmed.toLowerCase()] || trimmed;
  }
  if (normalizedProvider === 'ollama') {
    return normalizeOllamaModelName(trimmed);
  }
  return trimmed;
};

const TIGHT_EDIT_PRESET_OPTIONS = [
  {
    value: 'aggressive',
    label: 'Aggressiv',
    description: 'Schneidet Pausen und Füllwörter konsequent. Empfohlen für Short-Form.',
  },
  {
    value: 'balanced',
    label: 'Ausgewogen',
    description: 'Weniger sprunghaft, lässt etwas mehr Luft.',
  },
  {
    value: 'very_aggressive',
    label: 'Sehr aggressiv',
    description: 'Entfernt noch mehr Stille und Füllwörter. Für maximales Tempo.',
  },
  {
    value: 'off',
    label: 'Aus',
    description: 'Behält den originalen Sprachrhythmus.',
  },
];

const DEFAULT_TIGHT_EDIT_SETTINGS = {
  preset: 'aggressive',
};

const DEFAULT_YOUTUBE_AUTH_SETTINGS = {
  mode: 'auto',
  browser: 'auto',
  cookiesText: '',
};

const YOUTUBE_AUTH_MODE_OPTIONS = [
  { value: 'auto', label: 'Auto (inline -> cookies.txt -> Browser)' },
  { value: 'cookies_file', label: 'Nur cookies.txt Datei' },
  { value: 'cookies_text', label: 'Nur eingefügte Cookies' },
  { value: 'browser', label: 'Nur Browser-Profil' },
];

const YOUTUBE_BROWSER_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'chrome', label: 'Chrome' },
  { value: 'edge', label: 'Edge' },
  { value: 'brave', label: 'Brave' },
  { value: 'chromium', label: 'Chromium' },
  { value: 'firefox', label: 'Firefox' },
  { value: 'opera', label: 'Opera' },
  { value: 'vivaldi', label: 'Vivaldi' },
  { value: 'safari', label: 'Safari' },
];

const SUBTITLE_POSITION_PRESETS = [
  { value: 'top', label: 'Oben', y: 14 },
  { value: 'middle', label: 'Mitte', y: 50 },
  { value: 'bottom', label: 'Unten', y: 86 },
];

const HOOK_VERTICAL_PRESETS = {
  top: 12,
  center: 50,
  bottom: 88,
};

const HOOK_HORIZONTAL_PRESETS = {
  left: 18,
  center: 50,
  right: 82,
};

const HOOK_TEXT_ALIGN_OPTIONS = [
  { value: 'left', label: 'Links' },
  { value: 'center', label: 'Mitte' },
  { value: 'right', label: 'Rechts' },
];

const HOOK_SIZE_OPTIONS = [
  { value: 'S', label: 'Klein' },
  { value: 'M', label: 'Mittel' },
  { value: 'L', label: 'Groß' },
];

const clampPercent = (value, fallback = 50) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.min(100, Math.max(0, numeric));
};

const resolveSubtitlePositionFromY = (yPosition) => {
  const y = clampPercent(yPosition, SUBTITLE_POSITION_PRESETS[2].y);
  return SUBTITLE_POSITION_PRESETS.reduce((closest, preset) => (
    Math.abs(preset.y - y) < Math.abs(closest.y - y) ? preset : closest
  ), SUBTITLE_POSITION_PRESETS[2]).value;
};

const resolveHookGridToCoordinates = (gridValue) => {
  if (!gridValue || gridValue === 'center') {
    return {
      x: HOOK_HORIZONTAL_PRESETS.center,
      y: HOOK_VERTICAL_PRESETS.center,
      position: 'center',
      horizontalPosition: 'center',
      textAlign: 'center',
    };
  }
  const [verticalRaw, horizontalRaw = 'center'] = gridValue.split('-');
  const vertical = HOOK_VERTICAL_PRESETS[verticalRaw] !== undefined ? verticalRaw : 'center';
  const horizontal = HOOK_HORIZONTAL_PRESETS[horizontalRaw] !== undefined ? horizontalRaw : 'center';
  return {
    x: HOOK_HORIZONTAL_PRESETS[horizontal],
    y: HOOK_VERTICAL_PRESETS[vertical],
    position: vertical,
    horizontalPosition: horizontal,
    textAlign: horizontal,
  };
};

const resolveHookGridFromCoordinates = (xPosition, yPosition) => {
  const x = clampPercent(xPosition, HOOK_HORIZONTAL_PRESETS.center);
  const y = clampPercent(yPosition, HOOK_VERTICAL_PRESETS.top);
  const horizontal = x < 34 ? 'left' : x > 66 ? 'right' : 'center';
  const vertical = y < 34 ? 'top' : y > 66 ? 'bottom' : 'center';
  if (horizontal === 'center' && vertical === 'center') return 'center';
  return `${vertical}-${horizontal}`;
};

const sanitizeOverlayProfileId = (value) => {
  const normalized = String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return normalized || '';
};

const clampFontSize = (value, fallback = DEFAULT_SUBTITLE_STYLE.fontSize) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.max(18, Math.min(44, Math.round(numeric)));
};

const clampZoomFactor = (value, fallback = DEFAULT_HOOK_STYLE.zoomFactor) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.max(0, Math.min(2, Math.round(numeric * 100) / 100));
};

const normalizePatternFlashMode = (value, fallback = DEFAULT_HOOK_STYLE.flashMode || 'every_10s') => {
  const normalized = String(value || '').trim().toLowerCase().replace(/-/g, '_');
  const aliases = {
    off: 'none',
    false: 'none',
    disabled: 'none',
    no: 'none',
    never: 'none',
    initial: 'start',
    beginning: 'start',
    start_only: 'start',
    only_start: 'start',
    '30': 'every_30s',
    '30s': 'every_30s',
    every30: 'every_30s',
    every_30: 'every_30s',
    very_rare: 'every_30s',
    sehr_selten: 'every_30s',
    '20': 'every_20s',
    '20s': 'every_20s',
    every20: 'every_20s',
    every_20: 'every_20s',
    '10': 'every_10s',
    '10s': 'every_10s',
    every10: 'every_10s',
    every_10: 'every_10s',
    rare: 'every_10s',
    selten: 'every_10s',
    '8': 'every_8s',
    '8s': 'every_8s',
    every8: 'every_8s',
    every_8: 'every_8s',
    normal: 'every_8s',
    medium: 'every_8s',
    '5': 'every_5s',
    '5s': 'every_5s',
    every5: 'every_5s',
    every_5: 'every_5s',
    frequent: 'every_5s',
    haeufig: 'every_5s',
    häufig: 'every_5s',
  };
  const candidate = aliases[normalized] || normalized;
  return PATTERN_FLASH_MODE_OPTIONS.some((option) => option.value === candidate) ? candidate : fallback;
};

const normalizeSubtitleStyleConfig = (rawStyle = {}) => {
  const normalizedPositionInput = String(rawStyle.position || '').toLowerCase();
  const normalizedPosition = normalizedPositionInput === 'center' ? 'middle' : normalizedPositionInput;
  const fallbackYFromPosition = SUBTITLE_POSITION_PRESETS.find((item) => item.value === normalizedPosition)?.y;
  const rawYPosition = rawStyle.yPosition ?? rawStyle.y_position;
  const rawFontSize = rawStyle.fontSize ?? rawStyle.font_size;
  const rawFontFamily = rawStyle.fontFamily ?? rawStyle.font_family;
  const rawBackgroundStyle = rawStyle.backgroundStyle ?? rawStyle.background_style;
  const yPosition = rawYPosition !== undefined && rawYPosition !== null
    ? clampPercent(rawYPosition, DEFAULT_SUBTITLE_STYLE.yPosition)
    : (fallbackYFromPosition ?? DEFAULT_SUBTITLE_STYLE.yPosition);
  return {
    ...DEFAULT_SUBTITLE_STYLE,
    ...rawStyle,
    position: resolveSubtitlePositionFromY(yPosition),
    yPosition,
    fontSize: clampFontSize(rawFontSize, DEFAULT_SUBTITLE_STYLE.fontSize),
    fontFamily: rawFontFamily || DEFAULT_SUBTITLE_STYLE.fontFamily,
    backgroundStyle: rawBackgroundStyle || DEFAULT_SUBTITLE_STYLE.backgroundStyle,
  };
};

const normalizeHookStyleConfig = (rawStyle = {}) => {
  const rawHorizontal = String(rawStyle.horizontalPosition || rawStyle.horizontal_position || '').toLowerCase();
  const rawVertical = String(rawStyle.position || '').toLowerCase();
  const derivedXFromHorizontal = HOOK_HORIZONTAL_PRESETS[rawHorizontal];
  const derivedYFromVertical = HOOK_VERTICAL_PRESETS[rawVertical];
  const rawXPosition = rawStyle.xPosition ?? rawStyle.x_position;
  const rawYPosition = rawStyle.yPosition ?? rawStyle.y_position;
  const rawTextAlign = rawStyle.textAlign ?? rawStyle.text_align;
  const rawWidthPreset = rawStyle.widthPreset ?? rawStyle.width_preset;
  const rawFontFamily = rawStyle.fontFamily ?? rawStyle.font_family;
  const rawBackgroundStyle = rawStyle.backgroundStyle ?? rawStyle.background_style;
  const xPosition = rawXPosition !== undefined && rawXPosition !== null
    ? clampPercent(rawXPosition, DEFAULT_HOOK_STYLE.xPosition)
    : clampPercent(derivedXFromHorizontal, DEFAULT_HOOK_STYLE.xPosition);
  const yPosition = rawYPosition !== undefined && rawYPosition !== null
    ? clampPercent(rawYPosition, DEFAULT_HOOK_STYLE.yPosition)
    : clampPercent(derivedYFromVertical, DEFAULT_HOOK_STYLE.yPosition);
  const horizontalPosition = ['left', 'center', 'right'].includes(rawHorizontal)
    ? rawHorizontal
    : (xPosition < 34 ? 'left' : xPosition > 66 ? 'right' : 'center');
  const position = ['top', 'center', 'bottom'].includes(rawVertical)
    ? rawVertical
    : (yPosition < 34 ? 'top' : yPosition > 66 ? 'bottom' : 'center');
  const widthValues = new Set(HOOK_WIDTH_OPTIONS.map((option) => option.value));
  const textAlignInput = String(rawTextAlign || '').toLowerCase();
  const textAlign = ['left', 'center', 'right'].includes(textAlignInput)
    ? textAlignInput
    : horizontalPosition;
  const startZoomFactor = clampZoomFactor(rawStyle.startZoomFactor ?? rawStyle.start_zoom_factor, DEFAULT_HOOK_STYLE.startZoomFactor);
  const zoomFactor = Math.max(
    clampZoomFactor(rawStyle.zoomFactor ?? rawStyle.zoom_factor, DEFAULT_HOOK_STYLE.zoomFactor),
    startZoomFactor,
  );
  const flashMode = normalizePatternFlashMode(rawStyle.flashMode ?? rawStyle.flash_mode, DEFAULT_HOOK_STYLE.flashMode);
  return {
    ...DEFAULT_HOOK_STYLE,
    ...rawStyle,
    xPosition,
    yPosition,
    horizontalPosition,
    position,
    textAlign,
    size: ['S', 'M', 'L'].includes(rawStyle.size) ? rawStyle.size : DEFAULT_HOOK_STYLE.size,
    widthPreset: widthValues.has(rawWidthPreset) ? rawWidthPreset : DEFAULT_HOOK_STYLE.widthPreset,
    fontFamily: rawFontFamily || DEFAULT_HOOK_STYLE.fontFamily,
    backgroundStyle: rawBackgroundStyle || DEFAULT_HOOK_STYLE.backgroundStyle,
    startZoomFactor,
    zoomFactor,
    flashMode,
  };
};

const DEFAULT_OVERLAY_PROFILES = {
  default: {
    id: 'default',
    name: 'Standard',
    subtitleStyle: normalizeSubtitleStyleConfig({
      ...DEFAULT_SUBTITLE_STYLE,
      position: 'bottom',
      yPosition: 72,
    }),
    hookStyle: normalizeHookStyleConfig({
      ...DEFAULT_HOOK_STYLE,
      position: 'top',
      horizontalPosition: 'center',
      xPosition: 50,
      yPosition: 28,
      textAlign: 'center',
      size: 'M',
      widthPreset: 'wide',
    }),
  },
  interview: {
    id: 'interview',
    name: 'Interview',
    subtitleStyle: normalizeSubtitleStyleConfig({
      ...DEFAULT_SUBTITLE_STYLE,
      position: 'middle',
      yPosition: 50,
    }),
    hookStyle: normalizeHookStyleConfig({
      ...DEFAULT_HOOK_STYLE,
      position: 'top',
      horizontalPosition: 'right',
      xPosition: 82,
      yPosition: 28,
      textAlign: 'right',
      size: 'M',
      widthPreset: 'wide',
    }),
  },
};

const mergeOverlayProfilesWithDefaults = (profilesInput) => {
  const merged = {
    default: { ...DEFAULT_OVERLAY_PROFILES.default },
    interview: { ...DEFAULT_OVERLAY_PROFILES.interview },
  };
  if (!profilesInput || typeof profilesInput !== 'object') {
    return merged;
  }
  Object.entries(profilesInput).forEach(([rawId, rawProfile]) => {
    if (!rawProfile || typeof rawProfile !== 'object') return;
    const id = sanitizeOverlayProfileId(rawId);
    if (!id) return;
    const existing = merged[id];
    merged[id] = {
      id,
      name: String(rawProfile.name || existing?.name || id).trim() || id,
      subtitleStyle: normalizeSubtitleStyleConfig({
        ...(existing?.subtitleStyle || {}),
        ...(rawProfile.subtitleStyle || {}),
      }),
      hookStyle: normalizeHookStyleConfig({
        ...(existing?.hookStyle || {}),
        ...(rawProfile.hookStyle || {}),
      }),
    };
  });
  return merged;
};

const readStoredOverlayProfiles = () => {
  try {
    const raw = localStorage.getItem('overlay_profiles_v1');
    if (!raw) return mergeOverlayProfilesWithDefaults({});
    const parsed = JSON.parse(raw);
    return mergeOverlayProfilesWithDefaults(parsed);
  } catch (e) {
    return mergeOverlayProfilesWithDefaults({});
  }
};

const detectLikelyBrowser = () => {
  const ua = (navigator.userAgent || '').toLowerCase();
  if (ua.includes('edg/')) return 'edge';
  if (ua.includes('brave')) return 'brave';
  if (ua.includes('opr/') || ua.includes('opera')) return 'opera';
  if (ua.includes('vivaldi')) return 'vivaldi';
  if (ua.includes('firefox')) return 'firefox';
  if (ua.includes('safari') && !ua.includes('chrome')) return 'safari';
  if (ua.includes('chrome')) return 'chrome';
  return 'auto';
};

const parseTqdmPercent = (line) => {
  const match = line.match(/(\d{1,3}(?:\.\d+)?)%/);
  if (!match) return null;
  const value = Number(match[1]);
  if (!Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, value));
};

const estimateMobileProcessingProgress = (logs, status, jobState, elapsedSeconds) => {
  const normalizedJobState = String(jobState || '').toLowerCase();
  if (status !== 'processing' || normalizedJobState === 'completed' || normalizedJobState === 'partial') {
    return { percent: 100, title: 'Fertig', hint: 'Job abgeschlossen.' };
  }
  if (normalizedJobState === 'failed' || normalizedJobState === 'cancelled') {
    return { percent: 100, title: 'Abgeschlossen', hint: 'Job wurde beendet.' };
  }

  const lines = (logs || []).map((line) => String(line || ''));
  const lowered = lines.map((line) => line.toLowerCase());
  const joined = lowered.join('\n');

  if (
    joined.includes('process finished successfully') ||
    joined.includes('process cancelled.') ||
    joined.includes('process failed with exit code') ||
    joined.includes('execution error:') ||
    joined.includes('process exited with code')
  ) {
    return { percent: 100, title: 'Fertig', hint: 'Job abgeschlossen.' };
  }

  const lastMatchingLine = (needle) => {
    for (let i = lowered.length - 1; i >= 0; i -= 1) {
      if (lowered[i].includes(needle)) return lines[i];
    }
    return '';
  };

  const lastChunkLine = (() => {
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      if (lines[i].includes('Ollama chunk')) return lines[i];
    }
    return '';
  })();

  let percent = 6;
  let title = 'Job wird vorbereitet';
  let hint = 'Bitte kurz gedulden.';

  if (jobState === 'queued' || joined.includes('queued')) {
    percent = Math.max(percent, 8);
    title = 'In Warteschlange';
    hint = 'Worker startet gleich.';
  }

  if (joined.includes('downloading video from youtube') || joined.includes('downloading with auth=')) {
    percent = Math.max(percent, 14);
    title = 'Video wird geladen';
    hint = 'Quelle wird vorbereitet.';
  }

  if (joined.includes('transcribing video') || joined.includes('faster-whisper runtime ready')) {
    percent = Math.max(percent, 28);
    title = 'Transkription läuft';
    hint = 'Sprache und Text werden analysiert.';
  }

  if (joined.includes('whisper decoding')) {
    percent = Math.max(percent, 36);
    title = 'Transkription läuft';
    const decodeLine = lastMatchingLine('whisper decoding');
    const audioMatch = decodeLine.match(/audio=(\d{2}):(\d{2})/);
    if (audioMatch) {
      hint = `Bereits verarbeitet: ${audioMatch[1]}:${audioMatch[2]} Audio`;
    } else {
      hint = 'Audio wird weiter dekodiert.';
    }
  }

  if (joined.includes('analyzing with ollama') || joined.includes('analyzing with gemini') || joined.includes('analyzing with')) {
    percent = Math.max(percent, 50);
    title = 'KI analysiert virale Momente';
    hint = 'Zeitstempel werden ausgewählt.';
  }

  if (lastChunkLine) {
    const chunkMatch = lastChunkLine.match(/chunk\s+(\d+)\/(\d+)/i);
    if (chunkMatch) {
      const current = Number(chunkMatch[1]);
      const total = Number(chunkMatch[2]);
      if (Number.isFinite(current) && Number.isFinite(total) && total > 0) {
        const chunkProgress = 50 + ((Math.max(1, current) - 1) / total) * 14;
        percent = Math.max(percent, Math.min(64, chunkProgress));
        title = 'KI analysiert virale Momente';
        hint = `Analyse-Chunk ${current}/${total}`;
      }
    }
  }

  if (joined.includes('found') && joined.includes('viral clips')) {
    percent = Math.max(percent, 68);
    title = 'Clips gefunden';
    hint = 'Rendering startet.';
  }

  if (joined.includes('processing clip') || joined.includes('step 1: detecting scenes') || joined.includes('step 1: processing interview layout')) {
    percent = Math.max(percent, 74);
    title = 'Clip wird gerendert';
    hint = 'Szenen und Tracking werden verarbeitet.';
  }

  const frameLine = lastMatchingLine('processing:');
  const framePercent = parseTqdmPercent(frameLine);
  if (framePercent !== null) {
    percent = Math.max(percent, Math.min(92, 78 + framePercent * 0.14));
    title = 'Clip wird gerendert';
    hint = `Frame-Verarbeitung ${Math.round(framePercent)}%`;
  }

  if (joined.includes('step 5: extracting audio')) {
    percent = Math.max(percent, 93);
    title = 'Audio wird finalisiert';
    hint = 'Fast fertig.';
  }

  if (joined.includes('step 6: merging')) {
    percent = Math.max(percent, 95);
    title = 'Video wird zusammengeführt';
    hint = 'Fast geschafft.';
  }

  if (joined.includes('clip saved') || joined.includes('total execution time')) {
    percent = Math.max(percent, 97);
    title = 'Finalisierung läuft';
    hint = 'Ergebnisse werden geschrieben.';
  }

  const timeBasedFloor = Math.min(26, Math.floor((elapsedSeconds || 0) / 18));
  percent = Math.max(percent, timeBasedFloor);
  percent = Math.min(98, Math.max(4, Math.round(percent)));

  return { percent, title, hint };
};

function App() {
  const [apiKey, setApiKey] = useState(localStorage.getItem('gemini_key') || '');
  const [huggingFaceKey, setHuggingFaceKey] = useState(() => localStorage.getItem('huggingface_key') || '');
  const [openaiKey, setOpenaiKey] = useState(() => localStorage.getItem('openai_key') || '');
  const [claudeKey, setClaudeKey] = useState(() => localStorage.getItem('claude_key') || '');
  const [minimaxKey, setMinimaxKey] = useState(() => localStorage.getItem('minimax_key') || '');
  const [minimaxAuthMode, setMinimaxAuthMode] = useState(() => {
    const stored = localStorage.getItem('minimax_auth_mode');
    return stored === 'payg' ? 'payg' : 'token_plan';
  });
  const [midjourneyKey, setMidjourneyKey] = useState(() => localStorage.getItem('midjourney_key') || '');
  const [midjourneyBaseUrl, setMidjourneyBaseUrl] = useState(() => localStorage.getItem('midjourney_base_url') || '');
  const [llmProvider, setLlmProvider] = useState(() => normalizeShortformProvider(localStorage.getItem('llm_provider') || 'gemini'));
  const [geminiModel, setGeminiModel] = useState(() => normalizeShortformModel('gemini', localStorage.getItem('gemini_model')));
  const [openaiModel, setOpenaiModel] = useState(() => normalizeShortformModel('openai', localStorage.getItem('openai_model')));
  const [claudeModel, setClaudeModel] = useState(() => normalizeShortformModel('claude', localStorage.getItem('claude_model')));
  const [minimaxModel, setMinimaxModel] = useState(() => normalizeShortformModel('minimax', localStorage.getItem('minimax_model')));
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState(() => {
    const stored = localStorage.getItem('ollama_base_url');
    if (!stored || stored === 'http://host.docker.internal:11434') {
      return 'http://127.0.0.1:11434';
    }
    return stored;
  });
  const [ollamaModel, setOllamaModelState] = useState(
    normalizeShortformModel('ollama', localStorage.getItem('ollama_model'))
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
  const [pexelsKey, setPexelsKey] = useState(() => {
    const stored = localStorage.getItem('pexelsKey_v1');
    if (stored) return decrypt(stored);
    return '';
  });
  const [longformThumbnailPromptPresets, setLongformThumbnailPromptPresets] = useState(() =>
    normalizeLongformThumbnailPromptPresets(readStoredJson('longform_thumbnail_prompt_presets_v1', DEFAULT_LONGFORM_THUMBNAIL_PROMPTS))
  );
  const [longformThumbnailModelDefaults, setLongformThumbnailModelDefaults] = useState(() =>
    normalizeLongformThumbnailModelDefaults(readStoredJson('longform_thumbnail_model_defaults_v1', DEFAULT_LONGFORM_THUMBNAIL_MODEL_DEFAULTS))
  );
  const [longformAiDefaults, setLongformAiDefaults] = useState(() =>
    normalizeLongformAiDefaults(readStoredJson('longform_ai_defaults_v1', DEFAULT_LONGFORM_AI_DEFAULTS))
  );

  const [uploadUserId, setUploadUserId] = useState(() => localStorage.getItem('uploadUserId') || '');
  const [uploadProfileContexts, setUploadProfileContexts] = useState(() => readStoredJson('upload_profile_contexts_v1', {}));
  const [userProfiles, setUserProfiles] = useState([]); // List of {username, connected: []}
  const [uploadProfileStatus, setUploadProfileStatus] = useState(null); // { type: 'success' | 'error' | 'info', message: string }
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle, processing, complete, error
  const [jobState, setJobState] = useState('idle'); // queued, processing, partial, completed, failed
  const [results, setResults] = useState(null);
  const [logs, setLogs] = useState([]);
  const [logsVisible, setLogsVisible] = useState(true);
  const [processingMedia, setProcessingMedia] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard'); // dashboard, transcription, thumbnails, social-upload, history, settings
  const [historyJobs, setHistoryJobs] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [showUnassignedHistoryJobs, setShowUnassignedHistoryJobs] = useState(false);
  const [cancelingJobId, setCancelingJobId] = useState(null);
  const [deletingJobId, setDeletingJobId] = useState(null);
  const [reanalyzingJobId, setReanalyzingJobId] = useState(null);
  const [overlayProfiles, setOverlayProfiles] = useState(() => readStoredOverlayProfiles());
  const [activeOverlayProfileId, setActiveOverlayProfileId] = useState(() => {
    const stored = sanitizeOverlayProfileId(localStorage.getItem('overlay_active_profile_v1') || '');
    return stored || 'default';
  });
  const [overlayProfileNameDraft, setOverlayProfileNameDraft] = useState('');
  const [overlayProfileStatus, setOverlayProfileStatus] = useState(null);
  const [subtitleStyle, setSubtitleStyle] = useState(() => normalizeSubtitleStyleConfig(readStoredJson('subtitle_style_v1', DEFAULT_SUBTITLE_STYLE)));
  const [hookStyle, setHookStyle] = useState(() => normalizeHookStyleConfig(readStoredJson('hook_style_v1', DEFAULT_HOOK_STYLE)));
  const [tightEditSettings, setTightEditSettings] = useState(() => readStoredJson('tight_edit_settings_v1', DEFAULT_TIGHT_EDIT_SETTINGS));
  const [socialPostSettings, setSocialPostSettings] = useState(() => readStoredSocialPostSettings());
  const [podcastDmSettings, setPodcastDmSettings] = useState(() => readStoredPodcastDmSettings());
  const [isPodcastDmPanelOpen, setIsPodcastDmPanelOpen] = useState(false);
  const [youtubeAuthSettings, setYoutubeAuthSettings] = useState(() => {
    const stored = readStoredJson('youtube_auth_settings_v1', DEFAULT_YOUTUBE_AUTH_SETTINGS);
    const browser = stored.browser && stored.browser !== 'auto' ? stored.browser : detectLikelyBrowser();
    return {
      ...DEFAULT_YOUTUBE_AUTH_SETTINGS,
      ...stored,
      browser: browser || 'auto',
    };
  });
  const [youtubeAuthStatus, setYoutubeAuthStatus] = useState(null);
  const [youtubeAuthBusy, setYoutubeAuthBusy] = useState(false);
  const [settingsSyncCode, setSettingsSyncCode] = useState('');
  const [generatedSettingsSyncCode, setGeneratedSettingsSyncCode] = useState('');
  const [settingsSyncBusy, setSettingsSyncBusy] = useState(false);
  const [settingsSyncStatus, setSettingsSyncStatus] = useState(null);
  const [settingsSyncIncludeYoutubeCookies, setSettingsSyncIncludeYoutubeCookies] = useState(true);
  const settingsImportInputRef = useRef(null);
  const [deferPreviewLoading, setDeferPreviewLoading] = useState(() => localStorage.getItem('defer_preview_loading_v1') !== '0');
  const [clipVideoOverrides, setClipVideoOverrides] = useState({});
  const [jobOverlayDefaults, setJobOverlayDefaults] = useState({});
  const [jobSocialDefaults, setJobSocialDefaults] = useState({});
  const [isPodcastCommentTemplateEditing, setIsPodcastCommentTemplateEditing] = useState(false);

  // Sync state for original video playback
  const [syncedTime, setSyncedTime] = useState(0);
  const [isSyncedPlaying, setIsSyncedPlaying] = useState(false);
  const [syncTrigger, setSyncTrigger] = useState(0);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isMobileLiveAnalysisOpen, setIsMobileLiveAnalysisOpen] = useState(false);
  const [isDesktopLiveAnalysisOpen, setIsDesktopLiveAnalysisOpen] = useState(true);
  const [activeJobAnalysisContext, setActiveJobAnalysisContext] = useState({ profileName: '', profileContext: '', jobInstructions: '' });
  const [analysisContextSaving, setAnalysisContextSaving] = useState(false);
  const [isAnalysisContextOpen, setIsAnalysisContextOpen] = useState(false);
  const [processingStartedAt, setProcessingStartedAt] = useState(null);
  const [clipDurationFilter, setClipDurationFilter] = useState('all');
  const [clipRenderFilter, setClipRenderFilter] = useState('all');
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const [showUnpostedOnly, setShowUnpostedOnly] = useState(false);
  const [showFailedPostsOnly, setShowFailedPostsOnly] = useState(false);
  const [hideFillerStarts, setHideFillerStarts] = useState(false);
  const [selectedClipKeys, setSelectedClipKeys] = useState([]);
  const [clipHookDrafts, setClipHookDrafts] = useState({});
  const [bulkScheduleDate, setBulkScheduleDate] = useState(() => formatDateInputValue());
  const [bulkScheduleSlots, setBulkScheduleSlots] = useState('12:00, 15:00, 18:00');
  const [bulkScheduleDayInterval, setBulkScheduleDayInterval] = useState(1);
  const [bulkScheduleStaggerSlotsByDay, setBulkScheduleStaggerSlotsByDay] = useState(false);
  const [bulkSkipCount, setBulkSkipCount] = useState(0);
  const [bulkFirstComment, setBulkFirstComment] = useState('');
  const [isBulkSettingsOpen, setIsBulkSettingsOpen] = useState(false);
  const [isBulkBarCollapsed, setIsBulkBarCollapsed] = useState(false);
  const [isBulkOrderOpen, setIsBulkOrderOpen] = useState(false);
  const [isBulkScheduling, setIsBulkScheduling] = useState(false);
  const [bulkProgress, setBulkProgress] = useState(null);
  const [bulkStatus, setBulkStatus] = useState(null);
  const [bulkOperationMode, setBulkOperationMode] = useState(BULK_OPERATION_MODES.RENDER_AND_POST);
  const [bulkControlBusy, setBulkControlBusy] = useState('');
  const [draggedSelectedClipKey, setDraggedSelectedClipKey] = useState('');
  const [dragOverSelectedClipKey, setDragOverSelectedClipKey] = useState('');
  const [socialSyncBusy, setSocialSyncBusy] = useState(false);
  const [socialSyncStatus, setSocialSyncStatus] = useState(null);
  const [jobRescheduleAllBusy, setJobRescheduleAllBusy] = useState(false);
  const [isJobCalendarOpen, setIsJobCalendarOpen] = useState(false);
  const [jobCalendarLoading, setJobCalendarLoading] = useState(false);
  const [jobCalendarError, setJobCalendarError] = useState('');
  const [jobCalendarEvents, setJobCalendarEvents] = useState([]);
  const [isGlobalCalendarOpen, setIsGlobalCalendarOpen] = useState(false);
  const [globalCalendarLoading, setGlobalCalendarLoading] = useState(false);
  const [globalCalendarError, setGlobalCalendarError] = useState('');
  const [globalCalendarEvents, setGlobalCalendarEvents] = useState([]);
  const [globalCalendarPendingItems, setGlobalCalendarPendingItems] = useState([]);
  const [globalCalendarVendorComplete, setGlobalCalendarVendorComplete] = useState(false);
  const [podcastCampaignRepairBusy, setPodcastCampaignRepairBusy] = useState(false);
  const [podcastCampaignRepairStatus, setPodcastCampaignRepairStatus] = useState(null);
  const [globalScheduleBatch, setGlobalScheduleBatch] = useState(() => (
    readStoredJson(GLOBAL_SCHEDULE_BATCH_STORAGE_KEY, null)
  ));
  const [queueOverview, setQueueOverview] = useState(null);
  const [queueSubmitStatus, setQueueSubmitStatus] = useState(null);
  const [isQueueSubmitting, setIsQueueSubmitting] = useState(false);
  const [mediaInputResetToken, setMediaInputResetToken] = useState(0);
  const [isQueuePanelOpen, setIsQueuePanelOpen] = useState(true);

  const handleClipPlay = (startTime) => {
    setSyncedTime(startTime);
    setIsSyncedPlaying(true);
    setSyncTrigger(prev => prev + 1);
  };

  const handleClipPause = () => {
    setIsSyncedPlaying(false);
  };

  const handleTabSelect = (tab) => {
    setActiveTab(tab);
    setIsMobileSidebarOpen(false);
  };

  useEffect(() => {
    setIsMobileSidebarOpen(false);
  }, [activeTab]);

  useEffect(() => {
    if (!isMobileSidebarOpen) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setIsMobileSidebarOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isMobileSidebarOpen]);

  useEffect(() => {
    if (status === 'processing') {
      setIsMobileLiveAnalysisOpen(true);
      return;
    }
    if (status === 'complete' || status === 'error' || status === 'idle') {
      setIsMobileLiveAnalysisOpen(false);
    }
  }, [status, jobId]);

  useEffect(() => {
    if (status === 'processing') {
      setProcessingStartedAt((prev) => prev || Date.now());
      return;
    }
    setProcessingStartedAt(null);
  }, [status, jobId]);

  useEffect(() => {
    if (!jobId) {
      setJobCalendarEvents([]);
      setJobCalendarError('');
      setIsJobCalendarOpen(false);
      setSocialSyncStatus(null);
      setClipDurationFilter('all');
      setClipRenderFilter('all');
      setShowSelectedOnly(false);
      setShowUnpostedOnly(false);
      setShowFailedPostsOnly(false);
      setHideFillerStarts(false);
      setSelectedClipKeys([]);
      setClipHookDrafts({});
      setBulkProgress(null);
      setBulkStatus(null);
      setIsBulkSettingsOpen(false);
      setIsBulkBarCollapsed(false);
      setIsBulkOrderOpen(false);
      setBulkScheduleDate(formatDateInputValue());
      setBulkScheduleSlots('12:00, 15:00, 18:00');
      setBulkScheduleDayInterval(1);
      setBulkScheduleStaggerSlotsByDay(false);
      setBulkSkipCount(0);
      setBulkFirstComment('');
      setBulkOperationMode(BULK_OPERATION_MODES.RENDER_AND_POST);
      setDragOverSelectedClipKey('');
      setDraggedSelectedClipKey('');
      return;
    }

    const stored = readStoredJobUiState(jobId);
    setSocialSyncStatus(null);
    setJobCalendarEvents([]);
    setJobCalendarError('');
    setClipDurationFilter(stored?.clipDurationFilter || 'all');
    setClipRenderFilter(stored?.clipRenderFilter || 'all');
    setShowSelectedOnly(!!stored?.showSelectedOnly);
    setShowUnpostedOnly(!!stored?.showUnpostedOnly);
    setShowFailedPostsOnly(!!stored?.showFailedPostsOnly);
    setHideFillerStarts(!!stored?.hideFillerStarts);
    setSelectedClipKeys(Array.isArray(stored?.selectedClipKeys) ? stored.selectedClipKeys : []);
    setClipHookDrafts(stored?.clipHookDrafts && typeof stored.clipHookDrafts === 'object' ? stored.clipHookDrafts : {});
    setBulkProgress(null);
    setBulkStatus(null);
    setIsBulkSettingsOpen(!!stored?.isBulkSettingsOpen);
    setIsBulkBarCollapsed(!!stored?.isBulkBarCollapsed);
    setIsBulkOrderOpen(!!stored?.isBulkOrderOpen);
    setBulkScheduleDate(stored?.bulkScheduleDate || formatDateInputValue());
    setBulkScheduleSlots(stored?.bulkScheduleSlots || '12:00, 15:00, 18:00');
    setBulkScheduleDayInterval(Math.max(1, Number(stored?.bulkScheduleDayInterval) || 1));
    setBulkScheduleStaggerSlotsByDay(!!stored?.bulkScheduleStaggerSlotsByDay);
    setBulkSkipCount(Math.max(0, Number(stored?.bulkSkipCount) || 0));
    setBulkFirstComment(stored?.bulkFirstComment || '');
    setBulkOperationMode(
      Object.values(BULK_OPERATION_MODES).includes(stored?.bulkOperationMode)
        ? stored.bulkOperationMode
        : BULK_OPERATION_MODES.RENDER_AND_POST
    );
    setDraggedSelectedClipKey('');
    setDragOverSelectedClipKey('');
  }, [jobId]);

  const setOllamaModel = (value) => {
    setOllamaModelState(normalizeOllamaModelName(value));
  };

  const resolveCurrentProviderStatus = (providerOverride = null) => {
    const resolvedProvider = normalizeShortformProvider(providerOverride || llmProvider);
    if (resolvedProvider === 'gemini') return { ready: !!apiKey.trim(), label: 'Gemini-Key fehlt' };
    if (resolvedProvider === 'openai') return { ready: !!openaiKey.trim(), label: 'OpenAI-Key fehlt' };
    if (resolvedProvider === 'claude') return { ready: !!claudeKey.trim(), label: 'Claude-Key fehlt' };
    if (resolvedProvider === 'minimax') return { ready: !!minimaxKey.trim(), label: 'MiniMax-Key fehlt' };
    if (resolvedProvider === 'ollama') return { ready: !!ollamaBaseUrl.trim() && !!ollamaModel.trim(), label: 'Ollama-Konfiguration fehlt' };
    return { ready: true, label: '' };
  };

  const getOverlayProfileForId = (profileId) => {
    const normalized = sanitizeOverlayProfileId(profileId);
    if (normalized && overlayProfiles[normalized]) {
      return overlayProfiles[normalized];
    }
    return overlayProfiles.default || DEFAULT_OVERLAY_PROFILES.default;
  };

  const resolveInterviewProfileId = () => (
    overlayProfiles.interview ? 'interview' : (overlayProfiles.default ? 'default' : Object.keys(overlayProfiles)[0] || 'default')
  );

  const resolveProfileIdForJobRequest = (isInterviewMode) => (
    isInterviewMode ? resolveInterviewProfileId() : (overlayProfiles[activeOverlayProfileId] ? activeOverlayProfileId : 'default')
  );

  const buildOverlayDefaultsForProfile = (profileId) => {
    const normalizedProfileId = sanitizeOverlayProfileId(profileId);
    if (normalizedProfileId && normalizedProfileId === activeOverlayProfileId) {
      return {
        profileId: normalizedProfileId,
        subtitleStyle: normalizeSubtitleStyleConfig(subtitleStyle),
        hookStyle: normalizeHookStyleConfig(hookStyle),
      };
    }
    const profile = getOverlayProfileForId(profileId);
    return {
      profileId: profile.id || profileId || 'default',
      subtitleStyle: normalizeSubtitleStyleConfig(profile.subtitleStyle),
      hookStyle: normalizeHookStyleConfig(profile.hookStyle),
    };
  };

  const ensureJobOverlayDefaults = (targetJobId, profileIdHint, forceReplace = false) => {
    if (!targetJobId) return;
    const defaults = buildOverlayDefaultsForProfile(profileIdHint);
    setJobOverlayDefaults((prev) => {
      if (!forceReplace && prev[targetJobId]) return prev;
      return {
        ...prev,
        [targetJobId]: defaults,
      };
    });
  };

  const applyCurrentStylesToActiveOverlayProfile = () => {
    const targetId = overlayProfiles[activeOverlayProfileId] ? activeOverlayProfileId : 'default';
    const existing = getOverlayProfileForId(targetId);
    setOverlayProfiles((prev) => ({
      ...prev,
      [targetId]: {
        ...existing,
        id: targetId,
        name: existing.name || targetId,
        subtitleStyle: normalizeSubtitleStyleConfig(subtitleStyle),
        hookStyle: normalizeHookStyleConfig(hookStyle),
      },
    }));
    setOverlayProfileStatus({ type: 'success', message: `Profil "${existing.name || targetId}" aktualisiert.` });
  };

  const saveCurrentStylesAsNewOverlayProfile = () => {
    const rawName = (overlayProfileNameDraft || '').trim();
    if (!rawName) {
      setOverlayProfileStatus({ type: 'error', message: 'Bitte einen Profilnamen eingeben.' });
      return;
    }
    const baseId = sanitizeOverlayProfileId(rawName);
    if (!baseId) {
      setOverlayProfileStatus({ type: 'error', message: 'Profilname ist ungueltig.' });
      return;
    }

    let candidateId = baseId;
    let suffix = 2;
    while (overlayProfiles[candidateId]) {
      candidateId = `${baseId}_${suffix}`;
      suffix += 1;
    }

    const nextProfile = {
      id: candidateId,
      name: rawName,
      subtitleStyle: normalizeSubtitleStyleConfig(subtitleStyle),
      hookStyle: normalizeHookStyleConfig(hookStyle),
    };
    setOverlayProfiles((prev) => ({ ...prev, [candidateId]: nextProfile }));
    setActiveOverlayProfileId(candidateId);
    setOverlayProfileNameDraft('');
    setOverlayProfileStatus({ type: 'success', message: `Profil "${rawName}" gespeichert.` });
  };

  const applySubtitleDefaultsToJob = async (targetJobId, style) => {
    if (!targetJobId) return;
    const existing = jobOverlayDefaults[targetJobId] || buildOverlayDefaultsForProfile(activeOverlayProfileId);
    const nextDefaults = {
      ...existing,
      subtitleStyle: normalizeSubtitleStyleConfig(style || existing.subtitleStyle),
    };

    setJobOverlayDefaults((prev) => ({
      ...prev,
      [targetJobId]: nextDefaults,
    }));
    setResults((prev) => prev ? ({ ...prev, job_overlay_defaults: {
      ...(prev.job_overlay_defaults || {}),
      subtitle_style: buildSubtitleSettingsPayload(nextDefaults.subtitleStyle),
      hook_style: prev.job_overlay_defaults?.hook_style,
    } }) : prev);

    try {
      const res = await fetch(getApiUrl('/api/job/overlay-defaults'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: targetJobId,
          subtitle_style: buildSubtitleSettingsPayload(nextDefaults.subtitleStyle),
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const persistedDefaults = data.job_overlay_defaults || {};
      setJobOverlayDefaults((prev) => ({
        ...prev,
        [targetJobId]: {
          ...nextDefaults,
          subtitleStyle: normalizeSubtitleStyleConfig(persistedDefaults.subtitle_style || nextDefaults.subtitleStyle),
          hookStyle: normalizeHookStyleConfig(persistedDefaults.hook_style || nextDefaults.hookStyle),
        },
      }));
      setBulkStatus({ type: 'success', message: 'Untertitel-Defaults fuer diesen Job gespeichert.' });
    } catch (error) {
      setBulkStatus({ type: 'error', message: `Job-Defaults konnten nicht gespeichert werden: ${error.message}` });
    }
  };

  const applyHookDefaultsToJob = async (targetJobId, style) => {
    if (!targetJobId) return;
    const existing = jobOverlayDefaults[targetJobId] || buildOverlayDefaultsForProfile(activeOverlayProfileId);
    const nextDefaults = {
      ...existing,
      hookStyle: normalizeHookStyleConfig(style || existing.hookStyle),
    };

    setJobOverlayDefaults((prev) => ({
      ...prev,
      [targetJobId]: nextDefaults,
    }));
    setResults((prev) => prev ? ({ ...prev, job_overlay_defaults: {
      ...(prev.job_overlay_defaults || {}),
      subtitle_style: prev.job_overlay_defaults?.subtitle_style,
      hook_style: buildHookSettingsPayload(nextDefaults.hookStyle, 'Template'),
    } }) : prev);

    try {
      const res = await fetch(getApiUrl('/api/job/overlay-defaults'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: targetJobId,
          hook_style: buildHookSettingsPayload(nextDefaults.hookStyle, 'Template'),
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const persistedDefaults = data.job_overlay_defaults || {};
      setJobOverlayDefaults((prev) => ({
        ...prev,
        [targetJobId]: {
          ...nextDefaults,
          subtitleStyle: normalizeSubtitleStyleConfig(persistedDefaults.subtitle_style || nextDefaults.subtitleStyle),
          hookStyle: normalizeHookStyleConfig(persistedDefaults.hook_style || nextDefaults.hookStyle),
        },
      }));
      setBulkStatus({ type: 'success', message: 'Hook-Defaults fuer diesen Job gespeichert.' });
    } catch (error) {
      setBulkStatus({ type: 'error', message: `Job-Defaults konnten nicht gespeichert werden: ${error.message}` });
    }
  };

  const updateInstagramCollaboratorsDraftForJob = (targetJobId, value) => {
    if (!targetJobId) return;
    const normalizedValue = String(value || '');
    setJobSocialDefaults((prev) => ({
      ...prev,
      [targetJobId]: {
        ...(prev[targetJobId] || {}),
        instagramCollaborators: normalizedValue,
      },
    }));
    setResults((prev) => prev ? ({
      ...prev,
      job_social_defaults: {
        ...(prev.job_social_defaults || {}),
        instagram_collaborators: normalizedValue.trim() || null,
      },
    }) : prev);
  };

  const applyInstagramCollaboratorsToJob = async (targetJobId, value) => {
    if (!targetJobId) return { success: false, error: new Error('Kein Job aktiv.') };
    const normalizedValue = String(value || '').trim();

    setJobSocialDefaults((prev) => ({
      ...prev,
      [targetJobId]: {
        ...(prev[targetJobId] || {}),
        instagramCollaborators: normalizedValue,
      },
    }));
    setResults((prev) => prev ? ({
      ...prev,
      job_social_defaults: {
        ...(prev.job_social_defaults || {}),
        instagram_collaborators: normalizedValue || null,
      },
    }) : prev);

    try {
      const res = await fetch(getApiUrl('/api/job/social-defaults'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: targetJobId,
          instagram_collaborators: normalizedValue,
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const persistedDefaults = data.job_social_defaults || {};
      setJobSocialDefaults((prev) => ({
        ...prev,
        [targetJobId]: {
          ...(prev[targetJobId] || {}),
          instagramCollaborators: persistedDefaults.instagram_collaborators || '',
        },
      }));
      setBulkStatus({
        type: 'success',
        message: normalizedValue
          ? 'Instagram-Collaborator fuer diesen Job gespeichert.'
          : 'Instagram-Collaborator fuer diesen Job entfernt.',
      });
      return {
        success: true,
        instagramCollaborators: persistedDefaults.instagram_collaborators || '',
      };
    } catch (error) {
      setBulkStatus({ type: 'error', message: `Job-Collaborator konnte nicht gespeichert werden: ${error.message}` });
      return { success: false, error };
    }
  };

  const updatePodcastLinkDraftForJob = (targetJobId, patch = {}) => {
    if (!targetJobId) return;
    setJobSocialDefaults((prev) => {
      const existing = prev[targetJobId] || {};
      const next = {
        ...existing,
        podcastYoutubeUrl: patch.podcastYoutubeUrl !== undefined ? patch.podcastYoutubeUrl : existing.podcastYoutubeUrl || '',
        podcastKeyword: patch.podcastKeyword !== undefined ? patch.podcastKeyword : existing.podcastKeyword || podcastDmSettings.defaultKeyword || 'Video',
        podcastCommentTemplate: patch.podcastCommentTemplate !== undefined ? patch.podcastCommentTemplate : existing.podcastCommentTemplate || DEFAULT_PODCAST_COMMENT_TEMPLATE,
        podcastDmEnabled: patch.podcastDmEnabled !== undefined ? !!patch.podcastDmEnabled : existing.podcastDmEnabled === true,
      };
      return {
        ...prev,
        [targetJobId]: next,
      };
    });
    setResults((prev) => {
      if (!prev) return prev;
      const existingCampaign = prev.job_social_defaults?.podcast_link_campaign || {};
      return {
        ...prev,
        job_social_defaults: {
          ...(prev.job_social_defaults || {}),
          podcast_link_campaign: {
            ...existingCampaign,
            enabled: patch.podcastDmEnabled !== undefined ? !!patch.podcastDmEnabled : existingCampaign.enabled === true,
            link_url: patch.podcastYoutubeUrl !== undefined ? patch.podcastYoutubeUrl : existingCampaign.link_url || existingCampaign.youtube_url || '',
            youtube_url: patch.podcastYoutubeUrl !== undefined ? patch.podcastYoutubeUrl : existingCampaign.youtube_url || '',
            keyword: patch.podcastKeyword !== undefined ? patch.podcastKeyword : existingCampaign.keyword || podcastDmSettings.defaultKeyword || 'Video',
            comment_template: patch.podcastCommentTemplate !== undefined ? patch.podcastCommentTemplate : existingCampaign.comment_template || DEFAULT_PODCAST_COMMENT_TEMPLATE,
          },
        },
      };
    });
  };

  const applyPodcastLinkToJob = async (targetJobId, values = {}) => {
    if (!targetJobId) return { success: false, error: new Error('Kein Job aktiv.') };
    const youtubeUrl = String(values.podcastYoutubeUrl || '').trim();
    const keyword = String(values.podcastKeyword || podcastDmSettings.defaultKeyword || 'Video').trim() || 'Video';
    const commentTemplate = String(values.podcastCommentTemplate || DEFAULT_PODCAST_COMMENT_TEMPLATE).trim() || DEFAULT_PODCAST_COMMENT_TEMPLATE;
    const enabled = values.podcastDmEnabled === true;
    updatePodcastLinkDraftForJob(targetJobId, {
      podcastYoutubeUrl: youtubeUrl,
      podcastKeyword: keyword,
      podcastCommentTemplate: commentTemplate,
      podcastDmEnabled: enabled,
    });

    try {
      const res = await fetch(getApiUrl('/api/job/social-defaults'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: targetJobId,
          podcast_link_url: youtubeUrl,
          podcast_keyword: keyword,
          podcast_comment_template: commentTemplate,
          podcast_dm_enabled: enabled,
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const campaign = data.job_social_defaults?.podcast_link_campaign || {};
      setJobSocialDefaults((prev) => ({
        ...prev,
        [targetJobId]: {
          ...(prev[targetJobId] || {}),
          podcastYoutubeUrl: campaign.link_url || campaign.youtube_url || '',
          podcastKeyword: campaign.keyword || keyword,
          podcastCommentTemplate: campaign.comment_template || commentTemplate,
          podcastDmEnabled: campaign.enabled === true,
        },
      }));
      setResults((prev) => prev ? ({
        ...prev,
        job_social_defaults: data.job_social_defaults || prev.job_social_defaults || {},
      }) : prev);
      setBulkStatus({
        type: 'success',
        message: campaign.link_url
          ? 'Kommentar-DM-Link fuer diesen Job gespeichert.'
          : 'Kommentar-DM-Link fuer diesen Job entfernt.',
      });
      return { success: true, campaign };
    } catch (error) {
      setBulkStatus({ type: 'error', message: `Podcast-Link konnte nicht gespeichert werden: ${error.message}` });
      return { success: false, error };
    }
  };

  const activeJobOverlayDefaults = jobId
    ? (jobOverlayDefaults[jobId] || buildOverlayDefaultsForProfile(activeOverlayProfileId))
    : buildOverlayDefaultsForProfile(activeOverlayProfileId);
  const defaultJobSocialDefaults = {
    instagramCollaborators: '',
    podcastYoutubeUrl: '',
    podcastKeyword: podcastDmSettings.defaultKeyword || 'Video',
    podcastCommentTemplate: DEFAULT_PODCAST_COMMENT_TEMPLATE,
    podcastDmEnabled: false,
  };
  const activeJobSocialDefaults = jobId
    ? { ...defaultJobSocialDefaults, ...(jobSocialDefaults[jobId] || {}) }
    : defaultJobSocialDefaults;
  const activeJobUploadProfile = activeJobAnalysisContext.profileName || uploadUserId;

  useEffect(() => {
    if (!jobId || !results?.job_overlay_defaults) return;
    const persistedDefaults = results.job_overlay_defaults;
    setJobOverlayDefaults((prev) => {
      const existing = prev[jobId] || buildOverlayDefaultsForProfile(activeOverlayProfileId);
      return {
        ...prev,
        [jobId]: {
          ...existing,
          subtitleStyle: normalizeSubtitleStyleConfig(persistedDefaults.subtitle_style || existing.subtitleStyle),
          hookStyle: normalizeHookStyleConfig(persistedDefaults.hook_style || existing.hookStyle),
        },
      };
    });
  }, [jobId, results?.job_overlay_defaults, activeOverlayProfileId]);

  useEffect(() => {
    if (!jobId) return;
    const persistedDefaults = results?.job_social_defaults;
    if (!persistedDefaults) {
      setJobSocialDefaults((prev) => ({
        ...prev,
        [jobId]: {
          ...(prev[jobId] || {}),
          instagramCollaborators: prev[jobId]?.instagramCollaborators || '',
          podcastYoutubeUrl: prev[jobId]?.podcastYoutubeUrl || '',
          podcastKeyword: prev[jobId]?.podcastKeyword || podcastDmSettings.defaultKeyword || 'Video',
          podcastCommentTemplate: prev[jobId]?.podcastCommentTemplate || DEFAULT_PODCAST_COMMENT_TEMPLATE,
          podcastDmEnabled: prev[jobId]?.podcastDmEnabled === true,
        },
      }));
      return;
    }
    const campaign = persistedDefaults.podcast_link_campaign || {};
    setJobSocialDefaults((prev) => ({
      ...prev,
      [jobId]: {
        ...(prev[jobId] || {}),
        instagramCollaborators: persistedDefaults.instagram_collaborators || '',
        podcastYoutubeUrl: campaign.link_url || campaign.youtube_url || '',
        podcastKeyword: campaign.keyword || podcastDmSettings.defaultKeyword || 'Video',
        podcastCommentTemplate: campaign.comment_template || DEFAULT_PODCAST_COMMENT_TEMPLATE,
        podcastDmEnabled: campaign.enabled === true,
      },
    }));
  }, [jobId, results?.job_social_defaults, podcastDmSettings.defaultKeyword]);

  const getClipVariantKey = (activeJobId, clip, fallbackIndex) => buildClipSelectionKey(activeJobId, clip, fallbackIndex);

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

  useEffect(() => {
    if (!jobId || !results?.clips?.length) return;
    setClipHookDrafts((prev) => {
      const next = { ...prev };
      let changed = false;
      results.clips.forEach((clip, index) => {
        const key = buildClipSelectionKey(jobId, clip, index);
        if (next[key] === undefined) {
          next[key] = resolveClipHookDraftText(clip);
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [jobId, results?.clips]);

  const clipEntries = (results?.clips || []).map((clip, index) => {
    const key = buildClipSelectionKey(jobId || 'job', clip, index);
    return {
      clip,
      index,
      key,
      durationSeconds: resolveClipDurationSeconds(clip),
      hookDraftText: clipHookDrafts[key] ?? resolveClipHookDraftText(clip),
    };
  });

  const clipEntryMap = new Map(clipEntries.map((entry) => [entry.key, entry]));

  const availableClipKeysSignature = clipEntries.map((entry) => entry.key).join('|');

  useEffect(() => {
    if (!selectedClipKeys.length && !Object.keys(clipHookDrafts).length) return;
    const availableKeys = new Set(clipEntries.map((entry) => entry.key));
    setSelectedClipKeys((prev) => {
      const next = prev.filter((key) => availableKeys.has(key));
      return next.length === prev.length ? prev : next;
    });
    setClipHookDrafts((prev) => {
      let changed = false;
      const next = Object.entries(prev).reduce((acc, [key, value]) => {
        if (!availableKeys.has(key)) {
          changed = true;
          return acc;
        }
        acc[key] = value;
        return acc;
      }, {});
      return changed ? next : prev;
    });
  }, [availableClipKeysSignature]);

  useEffect(() => {
    if (showSelectedOnly && !selectedClipKeys.length) {
      setShowSelectedOnly(false);
    }
  }, [showSelectedOnly, selectedClipKeys.length]);

  const filteredClipEntries = clipEntries.filter((entry) => {
    if (clipDurationFilter === 'over_1m' && entry.durationSeconds <= 60) return false;
    if (clipDurationFilter === 'under_1m' && entry.durationSeconds > 60) return false;
    if (clipRenderFilter === 'rendered' && !isClipRendered(entry.clip)) return false;
    if (clipRenderFilter === 'unrendered' && isClipRendered(entry.clip)) return false;
    if (showSelectedOnly && !selectedClipKeys.includes(entry.key)) return false;
    if (showUnpostedOnly && isClipPostedOrQueued(entry.clip)) return false;
    if (showFailedPostsOnly && !isClipPostFailed(entry.clip)) return false;
    if (hideFillerStarts && Array.isArray(entry.clip?.quality_flags) && entry.clip.quality_flags.some((flag) => flag?.type === 'starts_with_filler')) return false;
    return true;
  });

  const selectedClipEntries = selectedClipKeys
    .map((key) => clipEntryMap.get(key))
    .filter(Boolean);

  const toggleClipSelection = (clip, index) => {
    const key = buildClipSelectionKey(jobId || 'job', clip, index);
    setSelectedClipKeys((prev) => (
      prev.includes(key)
        ? prev.filter((item) => item !== key)
        : [...prev, key]
    ));
  };

  const updateClipHookDraft = (clip, index, value) => {
    const key = buildClipSelectionKey(jobId || 'job', clip, index);
    setClipHookDrafts((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const selectAllVisibleClips = () => {
    const visibleKeys = filteredClipEntries.map((entry) => entry.key);
    if (!visibleKeys.length) return;
    setSelectedClipKeys((prev) => {
      const next = [...prev];
      visibleKeys.forEach((key) => {
        if (!next.includes(key)) next.push(key);
      });
      return next;
    });
  };

  const moveSelectedClipKey = (sourceKey, targetKey) => {
    if (!sourceKey || !targetKey || sourceKey === targetKey) return;
    setSelectedClipKeys((prev) => {
      const fromIndex = prev.indexOf(sourceKey);
      const toIndex = prev.indexOf(targetKey);
      if (fromIndex === -1 || toIndex === -1) return prev;
      return moveArrayItem(prev, fromIndex, toIndex);
    });
  };

  const handleSelectedClipDragStart = (event, clipKey) => {
    setDraggedSelectedClipKey(clipKey);
    setDragOverSelectedClipKey('');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', clipKey);
  };

  const handleSelectedClipDragOver = (event, clipKey) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    if (dragOverSelectedClipKey !== clipKey) {
      setDragOverSelectedClipKey(clipKey);
    }
  };

  const handleSelectedClipDrop = (event, targetKey) => {
    event.preventDefault();
    const sourceKey = event.dataTransfer.getData('text/plain') || draggedSelectedClipKey;
    moveSelectedClipKey(sourceKey, targetKey);
    setDraggedSelectedClipKey('');
    setDragOverSelectedClipKey('');
  };

  const handleSelectedClipDragEnd = () => {
    setDraggedSelectedClipKey('');
    setDragOverSelectedClipKey('');
  };

  const selectedPlatformsForBulk = Object.keys(socialPostSettings.platforms || {}).filter((platform) => socialPostSettings.platforms[platform]);
  const normalizedBulkSkipCount = Math.max(0, Math.min(selectedClipEntries.length, Number(bulkSkipCount) || 0));
  const bulkProcessEntries = selectedClipEntries.slice(normalizedBulkSkipCount);
  const currentBulkOperation = results?.bulk_operation || null;
  const bulkOperationIsRunning = isBulkOperationRunning(currentBulkOperation);
  const bulkOperationCanResume = isBulkOperationResumable(currentBulkOperation) && (
    Number(currentBulkOperation?.completed_count || 0) < Number(currentBulkOperation?.total_count || 0)
    || Number(currentBulkOperation?.failed_count || 0) > 0
  );

  useEffect(() => {
    if (!jobId) return;
    writeStoredJobUiState(jobId, {
      clipDurationFilter,
      clipRenderFilter,
      showSelectedOnly,
      showUnpostedOnly,
      showFailedPostsOnly,
      hideFillerStarts,
      selectedClipKeys,
      clipHookDrafts,
      bulkScheduleDate,
      bulkScheduleSlots,
      bulkScheduleDayInterval,
      bulkScheduleStaggerSlotsByDay,
      bulkSkipCount,
      bulkFirstComment,
      isBulkSettingsOpen,
      isBulkBarCollapsed,
      isBulkOrderOpen,
      bulkOperationMode,
    });
  }, [
    jobId,
    clipDurationFilter,
    clipRenderFilter,
    showSelectedOnly,
    showUnpostedOnly,
    showFailedPostsOnly,
    hideFillerStarts,
    selectedClipKeys,
    clipHookDrafts,
    bulkScheduleDate,
    bulkScheduleSlots,
    bulkScheduleDayInterval,
    bulkScheduleStaggerSlotsByDay,
    bulkSkipCount,
    bulkFirstComment,
    isBulkSettingsOpen,
    isBulkBarCollapsed,
    isBulkOrderOpen,
    bulkOperationMode,
  ]);

  let bulkSchedulePreview = [];
  let bulkSchedulePreviewError = '';
  try {
    if (selectedClipKeys.length >= 2 && bulkProcessEntries.length > 0) {
      bulkSchedulePreview = buildScheduledPostDates({
        slotText: bulkScheduleSlots,
        count: Math.min(20, bulkProcessEntries.length),
        startDate: bulkScheduleDate,
        dayInterval: bulkScheduleDayInterval,
        staggerSlotsByDay: bulkScheduleStaggerSlotsByDay,
        slotOffset: normalizedBulkSkipCount,
      });
    }
  } catch (error) {
    bulkSchedulePreviewError = error.message;
  }

  const showBulkActionsBar = activeTab === 'dashboard' && status === 'complete' && (
    selectedClipKeys.length >= 2
    || (currentBulkOperation && (bulkOperationIsRunning || bulkOperationCanResume))
  );

  const mergeBulkOperationIntoResults = (bulkOperation) => {
    if (!bulkOperation) return;
    setResults((prev) => prev ? ({
      ...prev,
      bulk_operation: bulkOperation,
    }) : prev);
  };

  const buildBulkRuntimePayload = () => ({
    provider: llmProvider,
    gemini_api_key: apiKey || undefined,
    openai_api_key: openaiKey || undefined,
    openai_model: openaiModel || undefined,
    claude_api_key: claudeKey || undefined,
    claude_model: claudeModel || undefined,
    minimax_api_key: minimaxKey || undefined,
    minimax_auth_mode: minimaxAuthMode || undefined,
    minimax_model: minimaxModel || undefined,
    gemini_model: geminiModel || undefined,
    ollama_base_url: ollamaBaseUrl || undefined,
    ollama_model: ollamaModel || undefined,
    pexels_api_key: pexelsKey || undefined,
    upload_post_api_key: uploadPostKey || undefined,
    upload_post_user_id: uploadUserId || undefined,
    podcast_dm_relay_url: podcastDmSettings.relayUrl || undefined,
    podcast_dm_relay_password: podcastDmSettings.relayPassword || undefined,
  });

  const handleBulkAction = async (operationMode = BULK_OPERATION_MODES.RENDER_AND_POST) => {
    const operationConfig = BULK_OPERATION_CONFIG[operationMode] || BULK_OPERATION_CONFIG[BULK_OPERATION_MODES.RENDER_AND_POST];
    const { requiresRender, requiresPost, label } = operationConfig;

    setBulkOperationMode(operationMode);

    if (!jobId) {
      setBulkStatus({ type: 'error', message: 'Kein aktiver Job geladen.' });
      return;
    }
    if (bulkOperationIsRunning) {
      setBulkStatus({ type: 'error', message: 'Es laeuft bereits ein Multi-Post-Task. Bitte zuerst pausieren oder stoppen.' });
      return;
    }
    if (bulkOperationCanResume) {
      setBulkStatus({ type: 'warning', message: 'Dieser Job hat noch einen pausierten oder unvollstaendigen Multi-Post. Bitte zuerst fortsetzen oder stoppen.' });
      return;
    }
    if (selectedClipEntries.length < 2) {
      setBulkStatus({ type: 'error', message: 'Bitte mindestens zwei Shorts auswaehlen.' });
      return;
    }
    if (!bulkProcessEntries.length) {
      setBulkStatus({ type: 'error', message: 'Der Skip-Wert ueberspringt bereits alle ausgewaehlten Shorts.' });
      return;
    }
    if (requiresPost && (!uploadPostKey || !uploadUserId)) {
      setBulkStatus({ type: 'error', message: 'Upload-Post API-Key oder Profil fehlt.' });
      return;
    }
    if (requiresPost && !selectedPlatformsForBulk.length) {
      setBulkStatus({ type: 'error', message: 'Bitte mindestens eine Plattform auswaehlen.' });
      return;
    }
    if (requiresPost && selectedPlatformsForBulk.includes('pinterest') && !(socialPostSettings.pinterestBoardId || '').trim()) {
      setBulkStatus({ type: 'error', message: 'Pinterest benoetigt eine Board-ID.' });
      return;
    }

    let scheduledDates = [];
    if (requiresPost) {
      try {
        scheduledDates = buildScheduledPostDates({
          slotText: bulkScheduleSlots,
          count: bulkProcessEntries.length,
          startDate: bulkScheduleDate,
          dayInterval: bulkScheduleDayInterval,
          staggerSlotsByDay: bulkScheduleStaggerSlotsByDay,
          slotOffset: normalizedBulkSkipCount,
        });
      } catch (error) {
        setBulkStatus({ type: 'error', message: error.message });
        return;
      }
    }

    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const invalidHookEntry = requiresRender
      ? bulkProcessEntries.find((entry) => !String(entry.hookDraftText || '').trim())
      : null;
    if (invalidHookEntry) {
      setBulkStatus({
        type: 'error',
        message: `Hook-Text fehlt bei Clip ${(invalidHookEntry.index || 0) + 1}.`,
      });
      return;
    }

    setIsBulkScheduling(true);
    setBulkStatus(null);
    setIsBulkSettingsOpen(false);

    try {
      const res = await fetch(getApiUrl('/api/bulk-operation/start'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: jobId,
          mode: operationMode,
          items: bulkProcessEntries.map((entry, position) => ({
            clip_index: entry.clip.clip_index ?? entry.index,
            clip_label: entry.clip.video_title_for_youtube_short || `Clip ${entry.index + 1}`,
            hook_text: String(entry.hookDraftText || '').trim(),
            scheduled_date: requiresPost ? scheduledDates[position].toISOString() : undefined,
          })),
          render: {
            apply_tight_edit: true,
            tight_edit_preset: tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset,
            apply_subtitles: true,
            subtitle_settings: buildSubtitleSettingsPayload(activeJobOverlayDefaults.subtitleStyle),
            apply_hook: true,
            hook_style: activeJobOverlayDefaults.hookStyle,
            pattern_flash_mode: activeJobOverlayDefaults.hookStyle?.flashMode || DEFAULT_HOOK_STYLE.flashMode,
            apply_stock_overlay: false,
          },
          post: {
            platforms: selectedPlatformsForBulk,
            first_comment: bulkFirstComment,
            timezone,
            instagram_share_mode: socialPostSettings.instagramShareMode,
            tiktok_post_mode: socialPostSettings.tiktokPostMode,
            tiktok_is_aigc: socialPostSettings.tiktokIsAigc,
            facebook_page_id: socialPostSettings.facebookPageId,
            pinterest_board_id: socialPostSettings.pinterestBoardId,
          },
          runtime: buildBulkRuntimePayload(),
        }),
      });

      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }

      const data = await res.json();
      mergeBulkOperationIntoResults(data.bulk_operation);
      setBulkProgress(null);
      setBulkStatus({
        type: 'success',
        message: `${label} wurde als fortsetzbarer Backend-Task gestartet.${normalizedBulkSkipCount ? ` ${normalizedBulkSkipCount} zuvor uebersprungen.` : ''}`,
      });
    } catch (error) {
      setBulkStatus({ type: 'error', message: error.message || `${label} konnte nicht gestartet werden.` });
    } finally {
      setIsBulkScheduling(false);
    }
  };

  const handlePauseBulkOperation = async () => {
    if (!jobId || !currentBulkOperation) return;
    setBulkControlBusy('pause');
    try {
      const res = await fetch(getApiUrl(`/api/bulk-operation/${jobId}/pause`), {
        method: 'POST',
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      mergeBulkOperationIntoResults(data.bulk_operation);
      setBulkStatus({ type: 'success', message: 'Multi-Post wird nach dem aktuellen Schritt pausiert.' });
    } catch (error) {
      setBulkStatus({ type: 'error', message: error.message || 'Multi-Post konnte nicht pausiert werden.' });
    } finally {
      setBulkControlBusy('');
    }
  };

  const handleResumeBulkOperation = async () => {
    if (!jobId || !currentBulkOperation) return;
    setBulkControlBusy('resume');
    try {
      const res = await fetch(getApiUrl(`/api/bulk-operation/${jobId}/resume`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          runtime: buildBulkRuntimePayload(),
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      mergeBulkOperationIntoResults(data.bulk_operation);
      setBulkStatus({ type: 'success', message: 'Multi-Post wird fortgesetzt.' });
    } catch (error) {
      setBulkStatus({ type: 'error', message: error.message || 'Multi-Post konnte nicht fortgesetzt werden.' });
    } finally {
      setBulkControlBusy('');
    }
  };

  const handleStopBulkOperation = async () => {
    if (!jobId || !currentBulkOperation) return;
    setBulkControlBusy('stop');
    try {
      const res = await fetch(getApiUrl(`/api/bulk-operation/${jobId}/stop`), {
        method: 'POST',
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      mergeBulkOperationIntoResults(data.bulk_operation);
      setBulkStatus({ type: 'warning', message: 'Multi-Post wurde gestoppt. Du kannst jetzt eine neue Multi-Post-Serie starten.' });
    } catch (error) {
      setBulkStatus({ type: 'error', message: error.message || 'Multi-Post konnte nicht gestoppt werden.' });
    } finally {
      setBulkControlBusy('');
    }
  };

  const buildProviderHeaders = (includeJson = false, providerOverride = null) => {
    const resolvedProvider = normalizeShortformProvider(providerOverride || llmProvider);
    const providerStatus = resolveCurrentProviderStatus(resolvedProvider);
    if (!providerStatus.ready) {
      throw new Error(`${providerStatus.label}. Bitte zuerst unter Einstellungen hinterlegen oder die Settings erneut importieren.`);
    }
    const headers = {
      'X-LLM-Provider': resolvedProvider
    };

    if (resolvedProvider === 'gemini') {
      headers['X-Gemini-Key'] = apiKey.trim();
      if (geminiModel) headers['X-Gemini-Model'] = geminiModel;
    }

    if (resolvedProvider === 'openai') {
      headers['X-OpenAI-Key'] = openaiKey.trim();
      if (openaiModel) headers['X-OpenAI-Model'] = openaiModel;
    }

    if (resolvedProvider === 'claude') {
      headers['X-Claude-Key'] = claudeKey.trim();
      if (claudeModel) headers['X-Claude-Model'] = claudeModel;
    }

    if (resolvedProvider === 'minimax') {
      headers['X-Minimax-Key'] = minimaxKey.trim();
      headers['X-Minimax-Auth-Mode'] = minimaxAuthMode;
      if (minimaxModel) headers['X-Minimax-Model'] = minimaxModel;
    }

    if (resolvedProvider === 'ollama') {
      headers['X-Ollama-Base-Url'] = ollamaBaseUrl;
      headers['X-Ollama-Model'] = ollamaModel;
    }

    if (pexelsKey) {
      headers['X-Pexels-Key'] = pexelsKey;
    }

    if (huggingFaceKey) {
      headers['X-HuggingFace-Key'] = huggingFaceKey;
    }

    if (includeJson) {
      headers['Content-Type'] = 'application/json';
    }

    return headers;
  };

  const buildYoutubeAuthPayload = () => {
    const mode = youtubeAuthSettings.mode || 'auto';
    const browser = youtubeAuthSettings.browser || 'auto';
    const payload = {
      youtube_auth_mode: mode,
      youtube_cookies_from_browser: browser,
    };
    if (mode === 'cookies_text' || (mode === 'auto' && (youtubeAuthSettings.cookiesText || '').trim())) {
      payload.youtube_cookies = youtubeAuthSettings.cookiesText || '';
    }
    return payload;
  };

  const refreshYoutubeAuthStatus = async () => {
    setYoutubeAuthBusy(true);
    try {
      const res = await fetch(getApiUrl('/api/youtube/auth/status'));
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setYoutubeAuthStatus(data);
    } catch (e) {
      setYoutubeAuthStatus({
        logged_in: false,
        error: e.message || 'Statusprüfung fehlgeschlagen',
      });
    } finally {
      setYoutubeAuthBusy(false);
    }
  };

  const saveYoutubeCookiesToBackend = async () => {
    if (!(youtubeAuthSettings.cookiesText || '').trim()) {
      alert('Bitte erst cookies.txt Inhalt einfuegen.');
      return;
    }
    setYoutubeAuthBusy(true);
    try {
      const res = await fetch(getApiUrl('/api/youtube/auth/cookies'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookies_text: youtubeAuthSettings.cookiesText }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setYoutubeAuthStatus(data);
      setYoutubeAuthSettings((prev) => ({ ...prev, mode: prev.mode === 'cookies_text' ? prev.mode : 'cookies_file' }));
    } catch (e) {
      alert(`Cookie-Speichern fehlgeschlagen: ${e.message}`);
    } finally {
      setYoutubeAuthBusy(false);
    }
  };

  const deleteYoutubeCookiesFromBackend = async () => {
    setYoutubeAuthBusy(true);
    try {
      const res = await fetch(getApiUrl('/api/youtube/auth/cookies'), {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setYoutubeAuthStatus(data);
    } catch (e) {
      alert(`Cookie Delete fehlgeschlagen: ${e.message}`);
    } finally {
      setYoutubeAuthBusy(false);
    }
  };

  const importYoutubeCookiesFromBrowser = async () => {
    setYoutubeAuthBusy(true);
    try {
      const selectedBrowser = youtubeAuthSettings.browser && youtubeAuthSettings.browser !== 'auto'
        ? youtubeAuthSettings.browser
        : detectLikelyBrowser();
      const res = await fetch(getApiUrl('/api/youtube/auth/import-browser'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ browser: selectedBrowser }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setYoutubeAuthStatus(data);
      setYoutubeAuthSettings((prev) => ({
        ...prev,
        browser: selectedBrowser,
        mode: prev.mode === 'cookies_text' ? 'auto' : prev.mode,
      }));
    } catch (e) {
      alert(`Browser-Cookie-Import fehlgeschlagen: ${e.message}`);
    } finally {
      setYoutubeAuthBusy(false);
    }
  };

  const collectSyncSettings = () => ({
    apiKey,
    huggingFaceKey,
    openaiKey,
    claudeKey,
    minimaxKey,
    minimaxAuthMode,
    midjourneyKey,
    midjourneyBaseUrl,
    llmProvider,
    geminiModel,
    openaiModel,
    claudeModel,
    minimaxModel,
    ollamaBaseUrl,
    ollamaModel,
    uploadPostKey,
    uploadUserId,
    elevenLabsKey,
    pexelsKey,
    subtitleStyle,
    hookStyle,
    overlayProfiles,
    activeOverlayProfileId,
    tightEditSettings,
    socialPostSettings,
    podcastDmSettings,
    youtubeAuthSettings,
    uploadProfileContexts,
    deferPreviewLoading,
    longformThumbnailPromptPresets,
    longformThumbnailModelDefaults,
    longformAiDefaults,
  });

  const applySyncedSettings = (payload) => {
    if (!payload || typeof payload !== 'object') return;

    const importedApiKey = typeof payload.apiKey === 'string' ? payload.apiKey : payload.gemini_api_key;
    const importedHuggingFaceKey = typeof payload.huggingFaceKey === 'string' ? payload.huggingFaceKey : payload.huggingface_token;
    const importedOpenaiKey = typeof payload.openaiKey === 'string' ? payload.openaiKey : payload.openai_api_key;
    const importedClaudeKey = typeof payload.claudeKey === 'string' ? payload.claudeKey : payload.claude_api_key;
    const importedMinimaxKey = typeof payload.minimaxKey === 'string' ? payload.minimaxKey : payload.minimax_api_key;
    const importedMinimaxAuthMode = payload.minimaxAuthMode || payload.minimax_auth_mode;
    const importedMidjourneyKey = typeof payload.midjourneyKey === 'string' ? payload.midjourneyKey : payload.midjourney_api_key;
    const importedMidjourneyBaseUrl = typeof payload.midjourneyBaseUrl === 'string' ? payload.midjourneyBaseUrl : payload.midjourney_base_url;
    const importedProvider = payload.llmProvider || payload.llm_provider || payload.provider;
    const importedGeminiModel = typeof payload.geminiModel === 'string' ? payload.geminiModel : payload.gemini_model;
    const importedOpenaiModel = typeof payload.openaiModel === 'string' ? payload.openaiModel : payload.openai_model;
    const importedClaudeModel = typeof payload.claudeModel === 'string' ? payload.claudeModel : payload.claude_model;
    const importedMinimaxModel = typeof payload.minimaxModel === 'string' ? payload.minimaxModel : payload.minimax_model;
    const importedOllamaBaseUrl = typeof payload.ollamaBaseUrl === 'string' ? payload.ollamaBaseUrl : payload.ollama_base_url;
    const importedOllamaModel = typeof payload.ollamaModel === 'string' ? payload.ollamaModel : payload.ollama_model;

    if (typeof importedApiKey === 'string') setApiKey(importedApiKey.trim());
    if (typeof importedHuggingFaceKey === 'string') setHuggingFaceKey(importedHuggingFaceKey.trim());
    if (typeof importedOpenaiKey === 'string') setOpenaiKey(importedOpenaiKey.trim());
    if (typeof importedClaudeKey === 'string') setClaudeKey(importedClaudeKey.trim());
    if (typeof importedMinimaxKey === 'string') setMinimaxKey(importedMinimaxKey.trim());
    if (importedMinimaxAuthMode === 'token_plan' || importedMinimaxAuthMode === 'payg') setMinimaxAuthMode(importedMinimaxAuthMode);
    if (typeof importedMidjourneyKey === 'string') setMidjourneyKey(importedMidjourneyKey.trim());
    if (typeof importedMidjourneyBaseUrl === 'string') setMidjourneyBaseUrl(importedMidjourneyBaseUrl.trim());
    if (importedProvider) setLlmProvider(normalizeShortformProvider(importedProvider));
    if (typeof importedGeminiModel === 'string') setGeminiModel(normalizeShortformModel('gemini', importedGeminiModel));
    if (typeof importedOpenaiModel === 'string') setOpenaiModel(normalizeShortformModel('openai', importedOpenaiModel));
    if (typeof importedClaudeModel === 'string') setClaudeModel(normalizeShortformModel('claude', importedClaudeModel));
    if (typeof importedMinimaxModel === 'string') setMinimaxModel(normalizeShortformModel('minimax', importedMinimaxModel));
    if (typeof importedOllamaBaseUrl === 'string' && importedOllamaBaseUrl.trim()) setOllamaBaseUrl(importedOllamaBaseUrl.trim());
    if (typeof importedOllamaModel === 'string' && importedOllamaModel.trim()) setOllamaModel(importedOllamaModel);
    if (typeof payload.uploadPostKey === 'string') setUploadPostKey(payload.uploadPostKey);
    if (typeof payload.uploadUserId === 'string') setUploadUserId(payload.uploadUserId);
    if (typeof payload.elevenLabsKey === 'string') setElevenLabsKey(payload.elevenLabsKey);
    if (typeof payload.pexelsKey === 'string') setPexelsKey(payload.pexelsKey);

    if (payload.subtitleStyle && typeof payload.subtitleStyle === 'object') {
      setSubtitleStyle(normalizeSubtitleStyleConfig(payload.subtitleStyle));
    }
    if (payload.hookStyle && typeof payload.hookStyle === 'object') {
      setHookStyle(normalizeHookStyleConfig(payload.hookStyle));
    }
    if (payload.overlayProfiles && typeof payload.overlayProfiles === 'object') {
      setOverlayProfiles(mergeOverlayProfilesWithDefaults(payload.overlayProfiles));
    }
    if (typeof payload.activeOverlayProfileId === 'string') {
      const requestedId = sanitizeOverlayProfileId(payload.activeOverlayProfileId);
      setActiveOverlayProfileId(requestedId || 'default');
    }
    if (payload.tightEditSettings && typeof payload.tightEditSettings === 'object') {
      setTightEditSettings({ ...DEFAULT_TIGHT_EDIT_SETTINGS, ...payload.tightEditSettings });
    }
    if (payload.socialPostSettings && typeof payload.socialPostSettings === 'object') {
      setSocialPostSettings({
        ...DEFAULT_SOCIAL_POST_SETTINGS,
        ...payload.socialPostSettings,
        platforms: {
          ...DEFAULT_SOCIAL_POST_SETTINGS.platforms,
          ...(payload.socialPostSettings.platforms || {}),
        },
      });
    }
    if (payload.podcastDmSettings && typeof payload.podcastDmSettings === 'object') {
      setPodcastDmSettings({
        ...DEFAULT_PODCAST_DM_SETTINGS,
        ...payload.podcastDmSettings,
      });
    }
    if (payload.youtubeAuthSettings && typeof payload.youtubeAuthSettings === 'object') {
      setYoutubeAuthSettings({
        ...DEFAULT_YOUTUBE_AUTH_SETTINGS,
        ...payload.youtubeAuthSettings,
        browser: payload.youtubeAuthSettings.browser || detectLikelyBrowser(),
      });
    }
    if (payload.uploadProfileContexts && typeof payload.uploadProfileContexts === 'object' && !Array.isArray(payload.uploadProfileContexts)) {
      setUploadProfileContexts(payload.uploadProfileContexts);
    }
    if (typeof payload.deferPreviewLoading === 'boolean') {
      setDeferPreviewLoading(payload.deferPreviewLoading);
    }
    if (Array.isArray(payload.longformThumbnailPromptPresets)) {
      setLongformThumbnailPromptPresets(normalizeLongformThumbnailPromptPresets(payload.longformThumbnailPromptPresets));
    }
    if (payload.longformThumbnailModelDefaults && typeof payload.longformThumbnailModelDefaults === 'object') {
      setLongformThumbnailModelDefaults(normalizeLongformThumbnailModelDefaults(payload.longformThumbnailModelDefaults));
    }
    if (payload.longformAiDefaults && typeof payload.longformAiDefaults === 'object') {
      setLongformAiDefaults(normalizeLongformAiDefaults(payload.longformAiDefaults));
    }
  };

  const exportSettingsToFile = () => {
    const confirmed = window.confirm(
      'Die Exportdatei enthält deine API-Schlüssel und das Relay-Passwort im Klartext. Nur sicher speichern und nicht weitergeben. Fortfahren?'
    );
    if (!confirmed) return;

    try {
      const settings = collectSyncSettings();
      if (!settingsSyncIncludeYoutubeCookies && settings.youtubeAuthSettings) {
        settings.youtubeAuthSettings = {
          ...settings.youtubeAuthSettings,
          cookiesText: '',
        };
      }
      const payload = {
        format: SETTINGS_EXPORT_FORMAT,
        version: SETTINGS_EXPORT_VERSION,
        exported_at: new Date().toISOString(),
        contains_secrets: true,
        includes_projects: false,
        includes_youtube_cookies: Boolean(
          settingsSyncIncludeYoutubeCookies && settings.youtubeAuthSettings?.cookiesText
        ),
        settings,
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      const date = new Date().toISOString().slice(0, 10);
      link.href = url;
      link.download = `openshorts-settings-${date}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setSettingsSyncStatus({
        type: 'success',
        message: 'Einstellungen exportiert. Projekte, Jobs und Medien sind nicht enthalten.',
      });
    } catch (error) {
      setSettingsSyncStatus({
        type: 'error',
        message: error.message || 'Einstellungen konnten nicht exportiert werden.',
      });
    }
  };

  const importSettingsFromFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (file.size > SETTINGS_EXPORT_MAX_BYTES) {
      setSettingsSyncStatus({ type: 'error', message: 'Die Einstellungsdatei ist größer als 2 MB.' });
      return;
    }

    setSettingsSyncBusy(true);
    setSettingsSyncStatus({ type: 'info', message: 'Einstellungsdatei wird geprüft...' });
    try {
      const payload = JSON.parse(await file.text());
      if (!payload || payload.format !== SETTINGS_EXPORT_FORMAT) {
        throw new Error('Keine gültige OpenShorts-Einstellungsdatei.');
      }
      if (Number(payload.version) !== SETTINGS_EXPORT_VERSION) {
        throw new Error(`Nicht unterstützte Einstellungsdatei-Version: ${payload.version ?? 'unbekannt'}.`);
      }
      if (!payload.settings || typeof payload.settings !== 'object' || Array.isArray(payload.settings)) {
        throw new Error('Die Einstellungsdatei enthält keinen gültigen Settings-Block.');
      }
      applySyncedSettings(payload.settings);
      setSettingsSyncStatus({
        type: 'success',
        message: payload.includes_youtube_cookies
          ? 'Einstellungen inklusive YouTube-Cookies importiert. Projekte wurden nicht übernommen.'
          : 'Einstellungen importiert. Projekte wurden nicht übernommen.',
      });
    } catch (error) {
      setSettingsSyncStatus({
        type: 'error',
        message: error instanceof SyntaxError
          ? 'Die ausgewählte Datei ist kein gültiges JSON.'
          : (error.message || 'Einstellungen konnten nicht importiert werden.'),
      });
    } finally {
      setSettingsSyncBusy(false);
    }
  };

  const createSettingsSyncCode = async () => {
    setSettingsSyncBusy(true);
    setSettingsSyncStatus({ type: 'info', message: 'Sync-Key wird erstellt...' });
    try {
      const res = await fetchWithTimeout(getApiUrl('/api/settings/sync/create'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          settings: collectSyncSettings(),
          include_youtube_cookies: settingsSyncIncludeYoutubeCookies,
        }),
      }, 12000);
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setGeneratedSettingsSyncCode(data.sync_code || '');
      setSettingsSyncCode(data.sync_code || '');
      setSettingsSyncStatus({
        type: 'success',
        message: `Sync-Code erstellt (${data.expires_in_days || 30} Tage gueltig).`,
      });
    } catch (e) {
      if (e?.name === 'AbortError') {
        setSettingsSyncStatus({ type: 'error', message: 'Sync-Erstellung abgelaufen. Bitte Netzwerk/Backend prüfen.' });
      } else {
        setSettingsSyncStatus({ type: 'error', message: e.message || 'Sync-Code konnte nicht erstellt werden.' });
      }
    } finally {
      setSettingsSyncBusy(false);
    }
  };

  const loadSettingsFromSyncCode = async () => {
    const code = (settingsSyncCode || '').replace(/\s+/g, '').trim();
    if (!code) {
      setSettingsSyncStatus({ type: 'error', message: 'Bitte Sync-Code eingeben.' });
      return;
    }
    setSettingsSyncBusy(true);
    setSettingsSyncStatus({ type: 'info', message: 'Sync-Key wird geladen...' });
    try {
      const res = await fetchWithTimeout(getApiUrl('/api/settings/sync/load'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sync_code: code, apply_youtube_cookies: true }),
      }, 12000);
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      applySyncedSettings(data.settings || {});
      if (data.youtube_cookies_applied) {
        await refreshYoutubeAuthStatus();
      }
      setSettingsSyncStatus({
        type: 'success',
        message: data.youtube_cookies_applied
          ? 'Einstellungen geladen. YouTube-Session wurde ebenfalls übernommen.'
          : 'Einstellungen geladen.',
      });
    } catch (e) {
      if (e?.name === 'AbortError') {
        setSettingsSyncStatus({ type: 'error', message: 'Sync-Laden abgelaufen. Bitte Netzwerk/Backend prüfen.' });
      } else {
        setSettingsSyncStatus({ type: 'error', message: e.message || 'Sync-Code konnte nicht geladen werden.' });
      }
    } finally {
      setSettingsSyncBusy(false);
    }
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
    if (!overlayProfiles[activeOverlayProfileId]) {
      setActiveOverlayProfileId('default');
      return;
    }
    const profile = overlayProfiles[activeOverlayProfileId];
    setSubtitleStyle(normalizeSubtitleStyleConfig(profile.subtitleStyle));
    setHookStyle(normalizeHookStyleConfig(profile.hookStyle));
  }, [overlayProfiles, activeOverlayProfileId]);

  useEffect(() => {
    localStorage.setItem('overlay_profiles_v1', JSON.stringify(overlayProfiles));
  }, [overlayProfiles]);

  useEffect(() => {
    localStorage.setItem('overlay_active_profile_v1', activeOverlayProfileId);
  }, [activeOverlayProfileId]);

  useEffect(() => {
    if (!overlayProfileStatus) return undefined;
    const timer = window.setTimeout(() => setOverlayProfileStatus(null), 3500);
    return () => window.clearTimeout(timer);
  }, [overlayProfileStatus]);

  useEffect(() => {
    // Encrypt Gemini Key too for consistency if desired, but user asked specifically about Social integration not saving well.
    // For now keeping gemini plain for compatibility unless requested.
    if (apiKey) localStorage.setItem('gemini_key', apiKey);
    else localStorage.removeItem('gemini_key');
  }, [apiKey]);

  useEffect(() => {
    if (huggingFaceKey) localStorage.setItem('huggingface_key', huggingFaceKey);
    else localStorage.removeItem('huggingface_key');
  }, [huggingFaceKey]);

  useEffect(() => {
    if (openaiKey) localStorage.setItem('openai_key', openaiKey);
    else localStorage.removeItem('openai_key');
  }, [openaiKey]);

  useEffect(() => {
    if (claudeKey) localStorage.setItem('claude_key', claudeKey);
    else localStorage.removeItem('claude_key');
  }, [claudeKey]);

  useEffect(() => {
    if (minimaxKey) localStorage.setItem('minimax_key', minimaxKey);
    else localStorage.removeItem('minimax_key');
  }, [minimaxKey]);

  useEffect(() => {
    localStorage.setItem('minimax_auth_mode', minimaxAuthMode);
  }, [minimaxAuthMode]);

  useEffect(() => {
    if (midjourneyKey) localStorage.setItem('midjourney_key', midjourneyKey);
    else localStorage.removeItem('midjourney_key');
  }, [midjourneyKey]);

  useEffect(() => {
    if (midjourneyBaseUrl) localStorage.setItem('midjourney_base_url', midjourneyBaseUrl);
    else localStorage.removeItem('midjourney_base_url');
  }, [midjourneyBaseUrl]);

  useEffect(() => {
    localStorage.setItem('llm_provider', llmProvider);
    localStorage.setItem('gemini_model', geminiModel);
    localStorage.setItem('openai_model', openaiModel);
    localStorage.setItem('claude_model', claudeModel);
    localStorage.setItem('minimax_model', minimaxModel);
    localStorage.setItem('ollama_base_url', ollamaBaseUrl);
    localStorage.setItem('ollama_model', ollamaModel);
  }, [claudeModel, geminiModel, llmProvider, minimaxModel, ollamaBaseUrl, ollamaModel, openaiModel]);

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
    localStorage.setItem('podcast_dm_settings_v1', JSON.stringify({
      ...podcastDmSettings,
      relayPassword: encrypt(podcastDmSettings.relayPassword || ''),
    }));
  }, [podcastDmSettings]);

  useEffect(() => {
    localStorage.setItem('upload_profile_contexts_v1', JSON.stringify(uploadProfileContexts));
  }, [uploadProfileContexts]);

  useEffect(() => {
    localStorage.setItem('youtube_auth_settings_v1', JSON.stringify(youtubeAuthSettings));
  }, [youtubeAuthSettings]);

  useEffect(() => {
    localStorage.setItem('longform_thumbnail_prompt_presets_v1', JSON.stringify(longformThumbnailPromptPresets));
  }, [longformThumbnailPromptPresets]);

  useEffect(() => {
    localStorage.setItem('longform_thumbnail_model_defaults_v1', JSON.stringify(longformThumbnailModelDefaults));
  }, [longformThumbnailModelDefaults]);

  useEffect(() => {
    localStorage.setItem('longform_ai_defaults_v1', JSON.stringify(longformAiDefaults));
  }, [longformAiDefaults]);

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
    if (pexelsKey) {
      localStorage.setItem('pexelsKey_v1', encrypt(pexelsKey));
    } else {
      localStorage.removeItem('pexelsKey_v1');
    }
  }, [pexelsKey]);

  useEffect(() => {
    localStorage.setItem('defer_preview_loading_v1', deferPreviewLoading ? '1' : '0');
  }, [deferPreviewLoading]);

  useEffect(() => {
    if (status === 'processing') setIsDesktopLiveAnalysisOpen(true);
    if (status === 'complete') setIsDesktopLiveAnalysisOpen(false);

    const lastLog = String(logs[logs.length - 1] || '');
    const canRecoverWithMinimax = resolveCurrentProviderStatus('minimax').ready;
    if (
      status === 'error'
      && !jobId
      && processingMedia
      && canRecoverWithMinimax
      && lastLog.includes('Missing X-Gemini-Key header')
    ) {
      const retryTimer = window.setTimeout(() => handleProcess(processingMedia, 'minimax'), 0);
      return () => window.clearTimeout(retryTimer);
    }

    return undefined;
  }, [status, jobId, logs, processingMedia, minimaxKey]);

  useEffect(() => {
    if (uploadPostKey && userProfiles.length === 0) {
      fetchUserProfiles();
    }
  }, [uploadPostKey]);

  useEffect(() => {
    let cancelled = false;
    const handleProviderStorageUpdate = (event) => {
      const value = String(event.newValue || '').trim();
      if (event.key === 'llm_provider' && value) setLlmProvider(normalizeShortformProvider(value));
      if (event.key === 'gemini_key') setApiKey(value);
      if (event.key === 'minimax_key') setMinimaxKey(value);
      if (event.key === 'minimax_auth_mode' && (value === 'token_plan' || value === 'payg')) setMinimaxAuthMode(value);
      if (event.key === 'minimax_model' && value) setMinimaxModel(normalizeShortformModel('minimax', value));
    };

    window.addEventListener('storage', handleProviderStorageUpdate);

    const urlParams = new URLSearchParams(window.location.search);
    const startupSyncCode = String(urlParams.get('settings_sync_code') || '').trim();
    if (startupSyncCode) {
      fetchWithTimeout(getApiUrl('/api/settings/sync/load'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sync_code: startupSyncCode, apply_youtube_cookies: false }),
      }, 12000)
        .then(async (res) => {
          if (!res.ok) throw new Error(await readErrorMessage(res));
          return res.json();
        })
        .then((data) => {
          if (cancelled) return;
          applySyncedSettings(data.settings || {});
          urlParams.delete('settings_sync_code');
          const nextSearch = urlParams.toString();
          window.history.replaceState(
            {},
            '',
            `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ''}${window.location.hash}`
          );
          setSettingsSyncStatus({ type: 'success', message: 'MiniMax-Einstellungen wurden übernommen.' });
        })
        .catch((error) => {
          if (!cancelled) {
            setSettingsSyncStatus({ type: 'error', message: error.message || 'Settings-Sync fehlgeschlagen.' });
          }
        });
    }

    if (activeTab === 'settings') {
      refreshYoutubeAuthStatus();
    }

    return () => {
      cancelled = true;
      window.removeEventListener('storage', handleProviderStorageUpdate);
    };
  }, [activeTab]);

  useEffect(() => {
    let interval;
    const shouldPollCurrentJob = !!jobId && (status === 'processing' || bulkOperationIsRunning);
    if (shouldPollCurrentJob) {
      interval = setInterval(async () => {
        try {
          const data = await pollJob(jobId);
          console.log("Job status:", data);

          if (data.result) {
            setResults(data.result);
          } else if (data.bulk_operation) {
            setResults((prev) => prev ? ({
              ...prev,
              bulk_operation: data.bulk_operation,
            }) : prev);
          }
          if (data.logs) {
            setLogs(data.logs);
          }
          if (data.job_state) {
            setJobState(data.job_state);
          }
          if (data.queue) {
            setQueueOverview(data.queue);
          }
          if (data.analysis_context) {
            setActiveJobAnalysisContext({
              profileName: data.analysis_context.profile_name || '',
              profileContext: data.analysis_context.profile_context || '',
              jobInstructions: data.analysis_context.job_instructions || '',
            });
          }

          const normalizedJobState = String(data.job_state || '').toLowerCase();
          const normalizedBulkStatus = String((data.bulk_operation || data.result?.bulk_operation || {}).status || '').toLowerCase();

          if (data.status === 'completed' || normalizedJobState === 'completed' || normalizedJobState === 'partial') {
            setStatus('complete');
            setJobState(data.job_state || 'completed');
          } else if (
            data.status === 'failed' ||
            data.status === 'cancelled' ||
            normalizedJobState === 'failed' ||
            normalizedJobState === 'cancelled'
          ) {
            setStatus('error');
            const errorMsg = data.error || (data.logs && data.logs.length > 0 ? data.logs[data.logs.length - 1] : "Process failed");
            setLogs(prev => [...prev, "Fehler: " + errorMsg]);
            setJobState(data.job_state || data.status || normalizedJobState || 'failed');
          }

          if (
            status !== 'processing'
            && !BULK_RUNNING_STATUSES.has(normalizedBulkStatus)
          ) {
            clearInterval(interval);
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [status, jobId, bulkOperationIsRunning]);

  const fetchJobHistory = async () => {
    setHistoryLoading(true);
    setHistoryError('');
    let timedOutByGuard = false;
    const failSafeTimer = window.setTimeout(() => {
      timedOutByGuard = true;
      setHistoryLoading(false);
      setHistoryError('Zeitüberschreitung beim Laden der Job-Historie. Bitte Backend-Erreichbarkeit prüfen.');
    }, 16000);
    try {
      const res = await fetchWithTimeout(
        getApiUrl(`/api/jobs/history?limit=100&include_result=false&include_logs=true&log_limit=30&upload_post_profile=${encodeURIComponent(showUnassignedHistoryJobs ? '__unassigned__' : uploadUserId || '')}`),
        {},
        10000
      );
      if (timedOutByGuard) {
        return;
      }
      if (!res.ok) {
        throw new Error('Job-Historie konnte nicht geladen werden');
      }
      const data = await res.json();
      if (timedOutByGuard) {
        return;
      }
      setHistoryJobs(data.jobs || []);
      setQueueOverview(data.queue || null);
    } catch (e) {
      if (timedOutByGuard) {
        return;
      }
      if (e?.name === 'AbortError') {
        setHistoryError('Zeitüberschreitung beim Laden der Job-Historie. Bitte Backend-Erreichbarkeit prüfen.');
      } else {
        setHistoryError(e.message || 'Job-Historie konnte nicht geladen werden');
      }
    } finally {
      window.clearTimeout(failSafeTimer);
      if (!timedOutByGuard) {
        setHistoryLoading(false);
      }
    }
  };

  useEffect(() => {
    if (activeTab === 'history') {
      fetchJobHistory();
    }
  }, [activeTab, uploadUserId, showUnassignedHistoryJobs]);

  useEffect(() => {
    if (activeTab !== 'history') return undefined;
    const interval = window.setInterval(() => {
      fetchJobHistory();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [activeTab, uploadUserId, showUnassignedHistoryJobs]);

  useEffect(() => {
    if (globalScheduleBatch?.operations?.length) {
      localStorage.setItem(GLOBAL_SCHEDULE_BATCH_STORAGE_KEY, JSON.stringify(globalScheduleBatch));
    }
  }, [globalScheduleBatch]);

  useEffect(() => {
    if (globalScheduleBatch?.operations?.length || !historyJobs.length) return;
    const runningPostOperations = historyJobs
      .map((job) => ({ jobId: job.job_id, operation: job.bulk_operation }))
      .filter(({ operation }) => (
        String(operation?.mode || '').toLowerCase() === BULK_OPERATION_MODES.POST_ONLY
        && isBulkOperationRunning(operation)
        && operation?.operation_id
      ));
    if (!runningPostOperations.length) return;
    const runningStartTimes = runningPostOperations
      .map(({ operation }) => Number(operation.started_at || 0))
      .filter((value) => Number.isFinite(value) && value > 0);
    const earliestStart = runningStartTimes.length ? Math.min(...runningStartTimes) : 0;
    const latestStart = runningStartTimes.length ? Math.max(...runningStartTimes) : 0;
    const recoveredBatchOperations = historyJobs
      .map((job) => ({ jobId: job.job_id, operation: job.bulk_operation }))
      .filter(({ operation }) => {
        if (String(operation?.mode || '').toLowerCase() !== BULK_OPERATION_MODES.POST_ONLY || !operation?.operation_id) {
          return false;
        }
        const startedAt = Number(operation.started_at || 0);
        return earliestStart > 0
          && startedAt >= earliestStart - 120
          && startedAt <= latestStart + 120;
      });
    const batchOperations = recoveredBatchOperations.length
      ? recoveredBatchOperations
      : runningPostOperations;
    setGlobalScheduleBatch({
      profile: uploadUserId,
      startedAt: new Date().toISOString(),
      operations: batchOperations.map(({ jobId: targetJobId, operation }) => ({
        jobId: targetJobId,
        operationId: operation.operation_id,
        totalCount: Number(operation.total_count || 0),
      })),
    });
  }, [globalScheduleBatch, historyJobs, uploadUserId]);

  const globalScheduleBatchProgress = useMemo(() => {
    const references = Array.isArray(globalScheduleBatch?.operations)
      ? globalScheduleBatch.operations
      : [];
    if (!references.length) return null;
    if (globalScheduleBatch?.profile && globalScheduleBatch.profile !== uploadUserId) return null;

    let totalCount = 0;
    let processedCount = 0;
    let failedCount = 0;
    let activeCount = 0;
    for (const reference of references) {
      const job = historyJobs.find((entry) => entry.job_id === reference.jobId);
      const operation = job?.bulk_operation;
      const matches = operation?.operation_id === reference.operationId;
      const operationTotal = Number(matches ? operation.total_count : reference.totalCount) || 0;
      totalCount += operationTotal;
      if (!matches) {
        if (operation?.operation_id) {
          // A newer operation can only replace a terminal one for the same job.
          processedCount += operationTotal;
        } else {
          activeCount += 1;
        }
        continue;
      }
      const operationFailed = Number(operation.failed_count || 0);
      const operationPosted = Number(operation.post_completed_count || 0);
      failedCount += operationFailed;
      processedCount += Math.min(operationTotal, operationPosted + operationFailed);
      if (isBulkOperationRunning(operation)) activeCount += 1;
    }

    const percent = totalCount > 0
      ? Math.max(0, Math.min(100, Math.round((processedCount / totalCount) * 100)))
      : 0;
    return {
      totalCount,
      processedCount,
      failedCount,
      activeCount,
      active: activeCount > 0,
      percent,
    };
  }, [globalScheduleBatch, historyJobs, uploadUserId]);


  const fetchUserProfiles = async () => {
    if (!uploadPostKey) {
      setUploadProfileStatus({ type: 'error', message: 'Bitte zuerst einen Upload-Post API-Key eingeben.' });
      setUserProfiles([]);
      return;
    }
    setUploadProfileStatus({ type: 'info', message: 'Profile werden geladen...' });
    try {
      const res = await fetch(getApiUrl('/api/social/user'), {
        headers: { 'X-Upload-Post-Key': uploadPostKey }
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      if (data.profiles && data.profiles.length > 0) {
        setUserProfiles(data.profiles);
        setUploadProfileStatus({ type: 'success', message: `${data.profiles.length} Profile geladen.` });
        // Auto select first if none selected
        if (!uploadUserId || !data.profiles.some((profile) => profile.username === uploadUserId)) {
          setUploadUserId(data.profiles[0].username);
        }
      } else {
        setUserProfiles([]);
        setUploadProfileStatus({
          type: data.recoverable ? 'info' : 'error',
          message: data.error || 'Keine Profile gefunden. Bitte API-Key und Upload-Post-Konto prüfen.',
        });
      }
    } catch (e) {
      setUploadProfileStatus({ type: 'error', message: `Fehler beim Laden der Profile: ${e.message}` });
      console.error(e);
    }
  };

  const applyJobSocialCalendarPayload = (targetJobId, data) => {
    if (targetJobId && targetJobId === jobId && data?.result) {
      setResults(data.result);
    }
    if (targetJobId && targetJobId === jobId && Array.isArray(data?.events)) {
      setJobCalendarEvents(data.events);
    }
  };

  const updateGlobalPendingCalendarItem = (targetJobId, updatedClip) => {
    if (!updatedClip) return;

    setGlobalCalendarPendingItems((prev) => prev.map((item) => {
      if (item.job_id !== targetJobId) return item;
      if ((item.clip_index ?? -1) !== (updatedClip.clip_index ?? -1)) return item;
      return {
        ...item,
        clip_label: updatedClip.video_title_for_youtube_short || item.clip_label,
        clip_title: updatedClip.video_title_for_youtube_short || item.clip_title,
        title: updatedClip.video_title_for_youtube_short || item.title,
        clip_description: updatedClip.video_description_for_instagram || updatedClip.video_description_for_tiktok || item.clip_description,
        description: updatedClip.video_description_for_instagram || updatedClip.video_description_for_tiktok || item.description,
        local_video_url: updatedClip.video_url || updatedClip.preview_video_url || item.local_video_url,
        local_preview_video_url: updatedClip.preview_video_url || updatedClip.video_url || item.local_preview_video_url,
        request_settings: {
          ...(item.request_settings || {}),
          title: updatedClip.video_title_for_youtube_short || item.title,
          description: updatedClip.video_description_for_instagram || updatedClip.video_description_for_tiktok || item.description,
          instagram_collaborators: updatedClip.instagram_collaborators || item.request_settings?.instagram_collaborators || '',
        },
        updated_at: Date.now() / 1000,
      };
    }));
  };

  const syncCurrentJobSocialPosts = async () => {
    if (!jobId) return;
    if (!uploadPostKey) {
      setSocialSyncStatus({ type: 'error', message: 'Bitte zuerst einen Upload-Post API-Key hinterlegen.' });
      return;
    }
    setSocialSyncBusy(true);
    setSocialSyncStatus({ type: 'info', message: 'Upload-Post-Status wird synchronisiert...' });
    try {
      const res = await fetch(getApiUrl(`/api/jobs/${jobId}/social/sync`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: uploadPostKey }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      applyJobSocialCalendarPayload(jobId, data);
      const failedClips = Number(data?.summary?.failed_clip_count || 0);
      setSocialSyncStatus({
        type: failedClips > 0 ? 'warning' : 'success',
        message: failedClips > 0
          ? `${failedClips} Clip${failedClips === 1 ? '' : 's'} mit fehlgeschlagenem Posting gefunden.`
          : 'Upload-Post-Status synchronisiert.',
      });
      fetchJobHistory();
    } catch (error) {
      setSocialSyncStatus({ type: 'error', message: error.message || 'Upload-Post-Sync fehlgeschlagen.' });
    } finally {
      setSocialSyncBusy(false);
    }
  };

  const loadJobCalendar = async (targetJobId = jobId) => {
    if (!targetJobId) return;
    if (!uploadPostKey) {
      setJobCalendarError('Bitte zuerst einen Upload-Post API-Key hinterlegen.');
      setIsJobCalendarOpen(true);
      return;
    }
    setIsJobCalendarOpen(true);
    setJobCalendarLoading(true);
    setJobCalendarError('');
    try {
      const res = await fetch(getApiUrl(`/api/jobs/${targetJobId}/social/calendar`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: uploadPostKey, sync: true }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      applyJobSocialCalendarPayload(targetJobId, data);
      setJobCalendarEvents(data.events || []);
      fetchJobHistory();
    } catch (error) {
      setJobCalendarError(error.message || 'Kalender konnte nicht geladen werden.');
    } finally {
      setJobCalendarLoading(false);
    }
  };

  const loadGlobalCalendar = async () => {
    if (!uploadPostKey) {
      setGlobalCalendarError('Bitte zuerst einen Upload-Post API-Key hinterlegen.');
      setIsGlobalCalendarOpen(true);
      return;
    }
    setIsGlobalCalendarOpen(true);
    setGlobalCalendarLoading(true);
    setGlobalCalendarError('');
    setGlobalCalendarVendorComplete(false);
    try {
      const res = await fetch(getApiUrl('/api/social/calendar'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: uploadPostKey, user_id: uploadUserId, sync: true, limit_jobs: 0 }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setGlobalCalendarEvents(data.events || []);
      setGlobalCalendarPendingItems(data.pending_items || []);
      setGlobalCalendarVendorComplete(data.vendor_calendar_complete === true);
      fetchJobHistory();
    } catch (error) {
      setGlobalCalendarVendorComplete(false);
      setGlobalCalendarError(error.message || 'Globaler Kalender konnte nicht geladen werden.');
    } finally {
      setGlobalCalendarLoading(false);
    }
  };

  const repairPodcastCampaignSchedules = async (options = {}) => {
    const targetProfile = String(options?.profileUsername || uploadUserId || '').trim();
    const targetJobIds = Array.isArray(options?.jobIds) ? options.jobIds.filter(Boolean) : [];
    if (!uploadPostKey || !targetProfile) {
      throw new Error('Upload-Post API-Key oder Profil fehlt.');
    }
    setPodcastCampaignRepairBusy(true);
    setPodcastCampaignRepairStatus({ type: 'info', message: 'Pruefe plattformspezifische Instagram-Texte und Relay-Registrierungen ...' });
    const requestRepair = async (execute) => {
      const res = await fetch(getApiUrl('/api/social/calendar/podcast-campaign/repair'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: uploadPostKey,
          user_id: targetProfile,
          execute,
          job_ids: targetJobIds.length ? targetJobIds : undefined,
          podcast_dm_relay_url: podcastDmSettings.relayUrl || undefined,
          podcast_dm_relay_password: podcastDmSettings.relayPassword || undefined,
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      return await res.json();
    };

    try {
      const preview = await requestRepair(false);
      if (!preview.eligible_count) {
        const scan = preview.scan || {};
        setPodcastCampaignRepairStatus({
          type: 'warning',
          message: `Keine reparierbaren Kampagnen-Posts gefunden. Scan: ${scan.events_scanned || 0} Events, ${scan.not_future || 0} nicht zukuenftig, ${scan.missing_campaign || 0} ohne Kampagne, ${scan.cannot_recreate || 0} ohne lokale Videodatei.`,
        });
        return;
      }
      if (preview.relay_repair_count > 0 && !preview.relay_configured) {
        throw new Error(
          `${preview.relay_repair_count} Relay-Registrierungen werden benoetigt. Bitte zuerst Relay-URL und Passwort in den Einstellungen hinterlegen.`,
        );
      }
      const scopeLabel = targetJobIds.length === 1 ? 'diesem Job' : `Profil "${targetProfile}"`;
      const confirmed = window.confirm(
        `${preview.caption_patch_count} zukuenftige Schedules bei ${scopeLabel} plattformspezifisch neu anlegen?\n\n`
        + 'Instagram erhaelt CTA + Leerzeile + KI-Text sowie die CTA im First Comment. Andere Plattformen behalten ihren normalen KI-Text.\n'
        + `${preview.relay_repair_count} neue oder fehlende Schedule-IDs werden im PHP-Relay registriert; ersetzte IDs werden entfernt.\n\n`
        + 'Hinweis: Die Neuanlage laedt die Videos erneut zu Upload-Post hoch und kann Upload-Kontingent verbrauchen. Alte Schedules werden erst nach erfolgreicher Neuanlage entfernt.',
      );
      if (!confirmed) {
        setPodcastCampaignRepairStatus(null);
        return;
      }
      setPodcastCampaignRepairStatus({ type: 'info', message: `${preview.eligible_count} Kampagnen-Posts werden plattformspezifisch repariert ...` });
      const result = await requestRepair(true);
      const summary = result.summary || {};
      const failed = Number(summary.caption_failed || 0) + Number(summary.relay_failed || 0);
      const firstFailure = (result.results || []).find((item) => (
        item?.caption_patch?.success === false || item?.relay_registration?.success === false
      ));
      const firstFailureMessage = firstFailure?.caption_patch?.error
        || firstFailure?.relay_registration?.message
        || firstFailure?.relay_registration?.error
        || '';
      const message = `${summary.caption_patched || 0} Schedules plattformspezifisch repariert, ${summary.relay_registered || 0} Relay-IDs registriert${failed ? `, ${failed} Fehler` : ''}.`
        + (firstFailureMessage ? ` Erster Fehler: ${firstFailureMessage}` : '');
      setPodcastCampaignRepairStatus({ type: failed ? 'warning' : 'success', message });
      if (targetJobIds.length) {
        fetchJobHistory();
      } else {
        await loadGlobalCalendar();
      }
      window.alert(message);
    } catch (error) {
      setPodcastCampaignRepairStatus({ type: 'error', message: error.message || 'Kampagnen-Reparatur fehlgeschlagen.' });
      if (targetJobIds.length) {
        window.alert(error.message || 'Kampagnen-Reparatur fehlgeschlagen.');
      }
      throw error;
    } finally {
      setPodcastCampaignRepairBusy(false);
    }
  };

  useEffect(() => {
    if (isGlobalCalendarOpen && uploadUserId) {
      loadGlobalCalendar();
    }
  }, [uploadUserId]);

  const saveCalendarEvent = async ({ event, payload, scope = 'job' }) => {
    if (!event) return;
    if (!uploadPostKey) throw new Error('Upload-Post API-Key fehlt.');
    const requiresLocalRecreate = (payload?.mode || '').toLowerCase() === 'recreate' && event?.can_recreate !== false;
    if (requiresLocalRecreate && !uploadUserId) throw new Error('Upload-Post Profil fehlt.');

    const res = await fetch(getApiUrl('/api/social/calendar/event/update'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: uploadPostKey,
        user_id: uploadUserId,
        job_id: event.job_id,
        clip_index: event.clip_index,
        vendor_job_id: event.vendor_job_id,
        event_source: event.event_source,
        history_entry_id: event.history_entry_id,
        podcast_dm_relay_url: podcastDmSettings.relayUrl || undefined,
        podcast_dm_relay_password: podcastDmSettings.relayPassword || undefined,
        ...payload,
      }),
    });
    if (!res.ok) throw new Error(await readErrorMessage(res));
    const data = await res.json();
    applyJobSocialCalendarPayload(event.job_id, data);
    if (Array.isArray(data?.events) && event.job_id === jobId) {
      setJobCalendarEvents(data.events);
    }
    if (scope === 'global') {
      await loadGlobalCalendar();
    } else if (event.job_id === jobId) {
      setJobCalendarEvents(data.events || []);
    }
    fetchJobHistory();
  };

  const deleteCalendarEvent = async (event, scope = 'job') => {
    if (!event) return;
    if (!uploadPostKey) throw new Error('Upload-Post API-Key fehlt.');
    const res = await fetch(getApiUrl('/api/social/calendar/event/delete'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: uploadPostKey,
        job_id: event.job_id,
        clip_index: event.clip_index,
        vendor_job_id: event.vendor_job_id,
        event_source: event.event_source,
        history_entry_id: event.history_entry_id,
      }),
    });
    if (!res.ok) throw new Error(await readErrorMessage(res));
    const data = await res.json();
    applyJobSocialCalendarPayload(event.job_id, data);
    if (scope === 'global') {
      await loadGlobalCalendar();
    } else if (event.job_id === jobId) {
      setJobCalendarEvents(data.events || []);
    }
    fetchJobHistory();
  };

  const resolveCalendarRemotePreview = async (event) => {
    if (!event?.vendor_job_id) return { preview_url: '' };
    if (!uploadPostKey) throw new Error('Upload-Post API-Key fehlt.');
    const res = await fetch(getApiUrl('/api/social/calendar/event/resolve-preview'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: uploadPostKey,
        user_id: uploadUserId || undefined,
        vendor_job_id: event.vendor_job_id,
      }),
    });
    if (!res.ok) throw new Error(await readErrorMessage(res));
    return await res.json();
  };

  const saveGlobalPendingCalendarItem = async ({ item, payload }) => {
    if (!item) return;
    const normalizedTitle = String(payload?.title ?? item.title ?? '').trim();
    const normalizedDescription = String(payload?.description ?? item.description ?? '').trim();
    const res = await fetch(getApiUrl('/api/clip/text-metadata'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: item.job_id,
        clip_index: item.clip_index,
        video_title_for_youtube_short: normalizedTitle,
        video_description_for_tiktok: normalizedDescription,
        video_description_for_instagram: normalizedDescription,
      }),
    });
    if (!res.ok) throw new Error(await readErrorMessage(res));
    const data = await res.json();
    if (data?.clip) {
      if (item.job_id === jobId) {
        updateClipResult(item.job_id, data.clip);
      }
      updateGlobalPendingCalendarItem(item.job_id, data.clip);
    }
  };

  const scheduleGlobalPendingCalendarItems = async ({ items, settings }) => {
    const selectedItems = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!selectedItems.length) {
      throw new Error('Bitte zuerst mindestens einen gelben Draft-Slot zuordnen.');
    }
    if (!uploadPostKey || !uploadUserId) {
      throw new Error('Upload-Post API-Key oder Profil fehlt.');
    }

    const selectedPlatforms = SOCIAL_PLATFORM_OPTIONS
      .filter((platform) => settings?.platforms?.[platform.key])
      .map((platform) => platform.key);

    if (!selectedPlatforms.length) {
      throw new Error('Bitte mindestens eine Plattform fuer den Sammel-Schedule auswaehlen.');
    }
    if (selectedPlatforms.includes('pinterest') && !(settings?.pinterestBoardId || '').trim()) {
      throw new Error('Pinterest benoetigt eine Board-ID.');
    }

    const minimumScheduleTime = Date.now() + (15 * 60 * 1000);
    const tooSoonItems = selectedItems.filter((item) => {
      const scheduledTime = new Date(item.assigned_scheduled_date || '').getTime();
      return !Number.isFinite(scheduledTime) || scheduledTime <= minimumScheduleTime;
    });
    if (tooSoonItems.length) {
      throw new Error(
        `${tooSoonItems.length} zugewiesene Slots beginnen in weniger als 15 Minuten. `
        + 'Bitte diese Drafts erneut automatisch verteilen oder spaeter einplanen.',
      );
    }

    const grouped = selectedItems.reduce((acc, item) => {
      const jobItems = acc.get(item.job_id) || [];
      jobItems.push(item);
      acc.set(item.job_id, jobItems);
      return acc;
    }, new Map());

    const runtime = buildBulkRuntimePayload();
    const timezone = settings?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

    const groupEntries = Array.from(grouped.entries());
    const responses = await Promise.all(groupEntries.map(async ([targetJobId, jobItems]) => {
      const chronologicalItems = [...jobItems].sort((left, right) => (
        new Date(left.assigned_scheduled_date || 0).getTime()
        - new Date(right.assigned_scheduled_date || 0).getTime()
      ));
      const res = await fetch(getApiUrl('/api/bulk-operation/start'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: targetJobId,
          mode: BULK_OPERATION_MODES.POST_ONLY,
          items: chronologicalItems.map((item) => ({
            clip_index: item.clip_index,
            clip_label: item.title || item.clip_label || `Clip ${Number(item.clip_index || 0) + 1}`,
            scheduled_date: item.assigned_scheduled_date,
          })),
          post: {
            platforms: selectedPlatforms,
            first_comment: settings?.firstComment || '',
            timezone,
            instagram_share_mode: settings?.instagramShareMode || socialPostSettings.instagramShareMode,
            tiktok_post_mode: settings?.tiktokPostMode || socialPostSettings.tiktokPostMode,
            tiktok_is_aigc: !!(settings?.tiktokIsAigc ?? socialPostSettings.tiktokIsAigc),
            facebook_page_id: settings?.facebookPageId || socialPostSettings.facebookPageId,
            pinterest_board_id: settings?.pinterestBoardId || socialPostSettings.pinterestBoardId,
          },
          runtime,
        }),
      });

      if (!res.ok) {
        return {
          ok: false,
          jobId: targetJobId,
          itemIds: chronologicalItems.map((item) => item.id),
          error: await readErrorMessage(res),
        };
      }

      const data = await res.json();
      updateHistoryJobBulkOperation(targetJobId, data.bulk_operation);
      return {
        ok: true,
        jobId: targetJobId,
        itemIds: chronologicalItems.map((item) => item.id),
        operation: data.bulk_operation,
      };
    }));

    const startedIds = responses.filter((entry) => entry.ok).flatMap((entry) => entry.itemIds);
    const startedOperations = responses
      .filter((entry) => entry.ok && entry.operation?.operation_id)
      .map((entry) => ({
        jobId: entry.jobId,
        operationId: entry.operation.operation_id,
        totalCount: Number(entry.operation.total_count || entry.itemIds.length || 0),
      }));
    const failedGroups = responses.filter((entry) => !entry.ok);

    if (startedIds.length) {
      setGlobalCalendarPendingItems((prev) => prev.filter((item) => !startedIds.includes(item.id)));
    }
    if (startedOperations.length) {
      setGlobalScheduleBatch({
        profile: uploadUserId,
        startedAt: new Date().toISOString(),
        operations: startedOperations,
      });
    }

    // Job history is cheap and carries live bulk progress. A complete vendor calendar
    // refresh can take minutes for a 12-month range and must not hold the start dialog open.
    void fetchJobHistory();

    return {
      startedIds,
      failedGroups,
    };
  };

  const rescheduleAllCurrentJobSocialPosts = async () => {
    if (!jobId) return;
    if (!uploadPostKey) {
      setSocialSyncStatus({ type: 'error', message: 'Bitte zuerst einen Upload-Post API-Key hinterlegen.' });
      return;
    }
    if (!uploadUserId) {
      setSocialSyncStatus({ type: 'error', message: 'Bitte zuerst ein Upload-Post Profil auswaehlen.' });
      return;
    }

    const confirmed = window.confirm(
      'Alle zukuenftigen Slots dieses Jobs wirklich neu hochladen und neu schedulen?\n\nDabei werden bestehende Upload-Post-Schedules ersetzt.',
    );
    if (!confirmed) return;

    setJobRescheduleAllBusy(true);
    setSocialSyncStatus({ type: 'info', message: 'Zukuenftige Slots werden neu hochgeladen und rescheduled...' });
    try {
      const res = await fetch(getApiUrl(`/api/jobs/${jobId}/social/reschedule-all`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: uploadPostKey,
          user_id: uploadUserId,
          sync: false,
          future_only: true,
          podcast_dm_relay_url: podcastDmSettings.relayUrl || undefined,
          podcast_dm_relay_password: podcastDmSettings.relayPassword || undefined,
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      applyJobSocialCalendarPayload(jobId, data);
      setJobCalendarEvents(data.events || []);
      const processedCount = Number(data?.rescheduled_count || 0);
      const failedCount = Number(data?.failed_count || 0);
      setSocialSyncStatus({
        type: failedCount > 0 ? 'warning' : 'success',
        message: failedCount > 0
          ? `${processedCount} Slots neu hochgeladen, ${failedCount} fehlgeschlagen.`
          : `${processedCount} zukuenftige Slots neu hochgeladen und rescheduled.`,
      });
      fetchJobHistory();
    } catch (error) {
      setSocialSyncStatus({ type: 'error', message: error.message || 'Reschedule all fehlgeschlagen.' });
    } finally {
      setJobRescheduleAllBusy(false);
    }
  };

  const handleProcess = async (data, providerOverride = null) => {
    if (isQueueSubmitting) return;
    const requestedProvider = normalizeShortformProvider(providerOverride || llmProvider);
    const resolvedProvider = resolveCurrentProviderStatus(requestedProvider).ready
      ? requestedProvider
      : (resolveCurrentProviderStatus('minimax').ready ? 'minimax' : requestedProvider);
    const providerStatus = resolveCurrentProviderStatus(resolvedProvider);
    if (!providerStatus.ready) {
      setQueueSubmitStatus({
        type: 'error',
        message: `${providerStatus.label}. Bitte zuerst unter Einstellungen hinterlegen oder die Settings erneut importieren.`,
      });
      return;
    }
    if (resolvedProvider !== llmProvider) {
      setLlmProvider(resolvedProvider);
    }
    const requestedProfileId = resolveProfileIdForJobRequest(!!data.options?.interviewMode);
    const activeUploadProfile = String(uploadUserId || '').trim();
    const activeProfileContext = String(uploadProfileContexts[activeUploadProfile] || '').trim();
    const shouldOpenQueuedJob = !jobId || status === 'idle';
    setIsQueueSubmitting(true);
    setQueueSubmitStatus({ type: 'info', message: 'Job wird vorbereitet und in die Warteschlange gestellt...' });
    if (shouldOpenQueuedJob) {
      setStatus('processing');
      setJobState('queued');
      setLogs(["Starting process..."]);
      setResults(null);
      setClipVideoOverrides({});
      setProcessingMedia({ ...data, overlayProfileId: requestedProfileId });
    }

    try {
      let body;
      const headers = buildProviderHeaders(data.type === 'url', resolvedProvider);

      if (data.type === 'url') {
        body = JSON.stringify({
          url: data.payload,
          interview_mode: !!data.options?.interviewMode,
          allow_long_clips: !!data.options?.allowLongClips,
          max_clips: Number(data.options?.maxClips) || 10,
          tight_edit_preset: tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset,
          analysis_only: !!data.options?.analysisOnly,
          upload_post_profile: activeUploadProfile,
          profile_context: activeProfileContext,
          job_instructions: data.options?.jobInstructions || '',
          destination_url: data.options?.destinationUrl || '',
          destination_keyword: data.options?.destinationKeyword || 'Video',
          ...buildYoutubeAuthPayload(),
        });
      } else {
        const formData = new FormData();
        formData.append('file', data.payload);
        formData.append('interview_mode', data.options?.interviewMode ? 'true' : 'false');
        formData.append('allow_long_clips', data.options?.allowLongClips ? 'true' : 'false');
        formData.append('max_clips', String(Number(data.options?.maxClips) || 10));
        formData.append('tight_edit_preset', tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset);
        formData.append('analysis_only', data.options?.analysisOnly ? 'true' : 'false');
        formData.append('upload_post_profile', activeUploadProfile);
        formData.append('profile_context', activeProfileContext);
        formData.append('job_instructions', data.options?.jobInstructions || '');
        formData.append('destination_url', data.options?.destinationUrl || '');
        formData.append('destination_keyword', data.options?.destinationKeyword || 'Video');
        const youtubePayload = buildYoutubeAuthPayload();
        formData.append('youtube_auth_mode', youtubePayload.youtube_auth_mode || 'auto');
        formData.append('youtube_cookies_from_browser', youtubePayload.youtube_cookies_from_browser || 'auto');
        if (youtubePayload.youtube_cookies) {
          formData.append('youtube_cookies', youtubePayload.youtube_cookies);
        }
        body = formData;
      }

      const res = await fetch(getApiUrl('/api/process'), {
        method: 'POST',
        headers: data.type === 'url' ? headers : { ...headers },
        body
      });

      if (!res.ok) throw new Error(await readErrorMessage(res));
      const resData = await res.json();
      if (shouldOpenQueuedJob) {
        setJobId(resData.job_id);
        setLogs([`Job ${resData.job_id} wurde eingereiht.`]);
      }
      ensureJobOverlayDefaults(resData.job_id, requestedProfileId, true);
      setMediaInputResetToken((value) => value + 1);
      const position = Number(resData.queue_position || 0);
      const positionText = position > 0 ? ` Position ${position} in der Queue.` : ' Startet sobald ein Worker-Slot frei ist.';
      setQueueSubmitStatus({
        type: 'success',
        message: `Job ${resData.job_id.slice(0, 8)} wurde eingereiht.${positionText}`,
      });
      if (resData.queue) {
        setQueueOverview(resData.queue);
      }
      fetchJobHistory();

    } catch (e) {
      if (shouldOpenQueuedJob) {
        setStatus('error');
        setJobState('failed');
        setLogs(l => [...l, `Fehler beim Starten des Jobs: ${e.message}`]);
      }
      setQueueSubmitStatus({ type: 'error', message: `Fehler beim Einreihen: ${e.message}` });
    } finally {
      setIsQueueSubmitting(false);
    }
  };

  const assignUploadProfileToJob = async (targetJob, profileName) => {
    const normalizedProfile = String(profileName || '').trim();
    const res = await fetch(getApiUrl(`/api/jobs/${targetJob.job_id}/analysis-context`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        upload_post_profile: normalizedProfile,
        profile_context: uploadProfileContexts[normalizedProfile] || '',
        job_instructions: targetJob.job_instructions || '',
      }),
    });
    if (!res.ok) throw new Error(await readErrorMessage(res));
    await fetchJobHistory();
  };

  const saveActiveJobAnalysisContext = async () => {
    if (!jobId) return;
    setAnalysisContextSaving(true);
    try {
      const profileName = activeJobAnalysisContext.profileName || uploadUserId || '';
      const res = await fetch(getApiUrl(`/api/jobs/${jobId}/analysis-context`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          upload_post_profile: profileName,
          profile_context: activeJobAnalysisContext.profileContext || uploadProfileContexts[profileName] || '',
          job_instructions: activeJobAnalysisContext.jobInstructions || '',
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      setQueueSubmitStatus({ type: 'success', message: 'Analysekontext gespeichert. Er gilt fuer den naechsten KI-Schritt oder eine Neuanalyse.' });
    } catch (error) {
      setQueueSubmitStatus({ type: 'error', message: error.message || 'Analysekontext konnte nicht gespeichert werden.' });
    } finally {
      setAnalysisContextSaving(false);
    }
  };

  const openActiveJobAnalysisContext = () => {
    const profileName = activeJobAnalysisContext.profileName || uploadUserId || '';
    setActiveJobAnalysisContext((previous) => ({
      ...previous,
      profileName,
      profileContext: previous.profileContext || uploadProfileContexts[profileName] || '',
    }));
    setIsAnalysisContextOpen(true);
  };

  const saveActiveProfileContext = () => {
    const profileName = String(activeJobAnalysisContext.profileName || uploadUserId || '').trim();
    if (!profileName) {
      setQueueSubmitStatus({ type: 'error', message: 'Bitte zuerst ein Upload-Post-Profil auswaehlen.' });
      return;
    }
    setUploadProfileContexts((previous) => ({
      ...previous,
      [profileName]: activeJobAnalysisContext.profileContext || '',
    }));
    setQueueSubmitStatus({
      type: 'success',
      message: `Kanalbeschreibung fuer Profil ${profileName} profiluebergreifend gespeichert. Sie wird bei neuen Jobs automatisch verwendet.`,
    });
  };

  const handleReset = () => {
    setStatus('idle');
    setJobState('idle');
    setJobId(null);
    setResults(null);
    setClipVideoOverrides({});
    setLogs([]);
    setProcessingMedia(null);
    setQueueSubmitStatus(null);
  };

  const handleOpenJob = async (job, options = {}) => {
    const openWithoutPreviews = !!options.openWithoutPreviews;
    try {
      const data = await pollJob(job.job_id);
      const requestMeta = job?.request || {};
      const profileIdForJob = resolveProfileIdForJobRequest(!!requestMeta.interview_mode);
      if (openWithoutPreviews) {
        setDeferPreviewLoading(true);
      }
      setJobId(job.job_id);
      setResults(data.result || job.result || null);
      setLogs(data.logs || job.logs || []);
      setProcessingMedia(deriveProcessingMedia(job));
      if (data.analysis_context) {
        setActiveJobAnalysisContext({
          profileName: data.analysis_context.profile_name || '',
          profileContext: data.analysis_context.profile_context || '',
          jobInstructions: data.analysis_context.job_instructions || '',
        });
      }
      ensureJobOverlayDefaults(job.job_id, profileIdForJob);
      setJobState(data.job_state || job.status || 'completed');
      setStatus(mapApiStatusToUi(data.status));
      setActiveTab('dashboard');
    } catch (e) {
      alert(`Job konnte nicht geöffnet werden: ${e.message}`);
    }
  };

  const handleOpenJobWithoutPreviews = async (job) => {
    await handleOpenJob(job, { openWithoutPreviews: true });
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
          upload_post_profile: job.job_id === jobId ? (activeJobAnalysisContext.profileName || uploadUserId) : (job.upload_post_profile || uploadUserId),
          profile_context: job.job_id === jobId ? activeJobAnalysisContext.profileContext : (job.profile_context || uploadProfileContexts[job.upload_post_profile || uploadUserId] || ''),
          job_instructions: job.job_id === jobId ? activeJobAnalysisContext.jobInstructions : (job.job_instructions || ''),
          ...buildYoutubeAuthPayload(),
        })
      });

      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }

      const data = await res.json();
      const requestMeta = job?.request || {};
      const profileIdForJob = resolveProfileIdForJobRequest(!!requestMeta.interview_mode);
      setJobId(data.job_id);
      setStatus('processing');
      setJobState('queued');
      setResults(job.result || null);
      setLogs((job.logs || []).concat([`Job ${job.job_id} wurde fortgesetzt und neu eingereiht.`]));
      setProcessingMedia(deriveProcessingMedia(job));
      ensureJobOverlayDefaults(data.job_id, profileIdForJob);
      setActiveTab('dashboard');
      fetchJobHistory();
    } catch (e) {
      alert(`Job konnte nicht fortgesetzt werden: ${e.message}`);
    }
  };

  const handleReanalyzeJobWithMinimax = async (job) => {
    if (!job?.job_id) return;
    if (!minimaxKey) {
      alert('MiniMax Token-Plan-Key fehlt in den Einstellungen.');
      return;
    }
    setReanalyzingJobId(job.job_id);
    try {
      const res = await fetch(getApiUrl(`/api/jobs/${job.job_id}/resume`), {
        method: 'POST',
        headers: buildProviderHeaders(true, 'minimax'),
        body: JSON.stringify({
          provider: 'minimax',
          minimax_model: minimaxModel,
          analysis_only: true,
          force_reanalysis: true,
          tight_edit_preset: tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset,
          upload_post_profile: job.job_id === jobId ? (activeJobAnalysisContext.profileName || uploadUserId) : (job.upload_post_profile || uploadUserId),
          profile_context: job.job_id === jobId ? activeJobAnalysisContext.profileContext : (job.profile_context || uploadProfileContexts[job.upload_post_profile || uploadUserId] || ''),
          job_instructions: job.job_id === jobId ? activeJobAnalysisContext.jobInstructions : (job.job_instructions || ''),
          ...buildYoutubeAuthPayload(),
        }),
      });

      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }

      const data = await res.json();
      const requestMeta = job?.request || {};
      const profileIdForJob = resolveProfileIdForJobRequest(!!requestMeta.interview_mode);
      const storedUiState = readStoredJobUiState(job.job_id) || {};
      writeStoredJobUiState(job.job_id, {
        ...storedUiState,
        selectedClipKeys: [],
        clipHookDrafts: {},
      });
      setJobId(data.job_id);
      setStatus('processing');
      setJobState('queued');
      setResults(null);
      setSelectedClipKeys([]);
      setClipHookDrafts({});
      setClipVideoOverrides((previous) => Object.fromEntries(
        Object.entries(previous).filter(([key]) => !key.startsWith(`${job.job_id}:`))
      ));
      setLogs((job.logs || []).concat([`Job ${job.job_id} wird mit MiniMax neu analysiert.`]));
      setProcessingMedia(deriveProcessingMedia(job));
      ensureJobOverlayDefaults(data.job_id, profileIdForJob);
      setActiveTab('dashboard');
      fetchJobHistory();
    } catch (e) {
      alert(`MiniMax-Reanalyse konnte nicht gestartet werden: ${e.message}`);
    } finally {
      setReanalyzingJobId(null);
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
      alert(`Job konnte nicht gestoppt werden: ${e.message}`);
    } finally {
      setCancelingJobId(null);
    }
  };

  const handleDeleteJob = async (job) => {
    if (!job?.job_id) return;
    const confirmed = window.confirm(`Job wirklich loeschen?\n\n${job.source_label || job.job_id}\n\nDer komplette Output-Ordner wird entfernt.`);
    if (!confirmed) return;

    setDeletingJobId(job.job_id);
    try {
      const res = await fetch(getApiUrl(`/api/jobs/${job.job_id}`), {
        method: 'DELETE',
      });

      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }

      if (job.job_id === jobId) {
        handleReset();
      }

      setHistoryJobs((prev) => prev.filter((entry) => entry.job_id !== job.job_id));
      fetchJobHistory();
    } catch (e) {
      alert(`Job konnte nicht gelöscht werden: ${e.message}`);
    } finally {
      setDeletingJobId(null);
    }
  };

  const updateHistoryJobBulkOperation = (targetJobId, bulkOperation) => {
    setHistoryJobs((prev) => prev.map((entry) => (
      entry.job_id === targetJobId
        ? { ...entry, bulk_operation: bulkOperation }
        : entry
    )));
    if (jobId === targetJobId) {
      mergeBulkOperationIntoResults(bulkOperation);
    }
  };

  const handlePauseBulkOperationFromHistory = async (job) => {
    if (!job?.job_id) return;
    setBulkControlBusy(`history-pause:${job.job_id}`);
    try {
      const res = await fetch(getApiUrl(`/api/bulk-operation/${job.job_id}/pause`), {
        method: 'POST',
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      updateHistoryJobBulkOperation(job.job_id, data.bulk_operation);
      fetchJobHistory();
    } catch (e) {
      alert(`Multi-Post konnte nicht pausiert werden: ${e.message}`);
    } finally {
      setBulkControlBusy('');
    }
  };

  const handleResumeBulkOperationFromHistory = async (job) => {
    if (!job?.job_id) return;
    const operation = job.bulk_operation || {};
    const operationStatus = String(operation.status || '').toLowerCase();
    const failedItems = (operation.items || []).filter((item) => item.post_status === 'failed');
    if (['partial', 'failed'].includes(operationStatus) && failedItems.length > 0) {
      const ambiguousFailures = failedItems.filter((item) => /gateway timeout|client closed request/i.test(item.last_error || ''));
      const pastSchedules = failedItems.filter((item) => {
        const scheduledTime = new Date(item.scheduled_date || '').getTime();
        return Number.isFinite(scheduledTime) && scheduledTime <= Date.now();
      });
      const warningLines = [
        `${failedItems.length} fehlgeschlagene Posts dieses Jobs erneut versuchen?`,
        '',
        'Bereits erfolgreiche Posts werden übersprungen.',
      ];
      if (ambiguousFailures.length > 0) {
        warningLines.push(
          '',
          `${ambiguousFailures.length} Fehler sind Timeouts/abgebrochene Client-Anfragen. `
          + 'Bei älteren Operationen könnte Upload-Post sie trotzdem angenommen haben. Bitte vorher den Kalender synchronisieren, um Doppelposts auszuschließen.',
        );
      }
      if (pastSchedules.length > 0) {
        warningLines.push('', 'Vergangene Retry-Termine werden automatisch gemeinsam in die Zukunft verschoben.');
      }
      if (!window.confirm(warningLines.join('\n'))) return;
    }
    setBulkControlBusy(`history-resume:${job.job_id}`);
    try {
      const res = await fetch(getApiUrl(`/api/bulk-operation/${job.job_id}/resume`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          runtime: buildBulkRuntimePayload(),
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      updateHistoryJobBulkOperation(job.job_id, data.bulk_operation);
      fetchJobHistory();
    } catch (e) {
      alert(`Multi-Post konnte nicht fortgesetzt werden: ${e.message}`);
    } finally {
      setBulkControlBusy('');
    }
  };

  const handleStopBulkOperationFromHistory = async (job) => {
    if (!job?.job_id) return;
    setBulkControlBusy(`history-stop:${job.job_id}`);
    try {
      const res = await fetch(getApiUrl(`/api/bulk-operation/${job.job_id}/stop`), {
        method: 'POST',
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      updateHistoryJobBulkOperation(job.job_id, data.bulk_operation);
      fetchJobHistory();
    } catch (e) {
      alert(`Multi-Post konnte nicht gestoppt werden: ${e.message}`);
    } finally {
      setBulkControlBusy('');
    }
  };

  // --- UI Components ---

  const Sidebar = ({ mobile = false }) => (
    <div className={`${mobile ? 'w-72 max-w-[88vw]' : 'w-20 lg:w-64'} bg-surface border-r border-white/5 flex flex-col h-full shrink-0 transition-all duration-300`}>
      <div className="p-6 flex items-center gap-3">
        <div className="w-8 h-8 bg-white/5 rounded-lg flex items-center justify-center shrink-0 overflow-hidden border border-white/5">
          <img src="/logo-openshorts.png" alt="Logo" className="w-full h-full object-cover" />
        </div>
        <span className={`font-bold text-lg text-white tracking-tight ${mobile ? 'block' : 'hidden lg:block'}`}>OpenShorts</span>
      </div>

      <nav className="flex-1 px-4 py-4 space-y-2 overflow-y-auto custom-scrollbar touch-scroll">
        <button
          onClick={() => handleTabSelect('dashboard')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'dashboard' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <LayoutDashboard size={20} />
          <span className={`font-medium ${mobile ? 'block' : 'hidden lg:block'}`}>Dashboard</span>
        </button>

        <button
          onClick={() => handleTabSelect('history')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'history' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <History size={20} />
          <span className={`font-medium ${mobile ? 'block' : 'hidden lg:block'}`}>Verlauf</span>
        </button>

        <button
          onClick={() => handleTabSelect('thumbnails')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'thumbnails' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <Image size={20} />
          <span className={`font-medium ${mobile ? 'block' : 'hidden lg:block'}`}>YouTube Studio</span>
        </button>

        <button
          onClick={() => handleTabSelect('transcription')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'transcription' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <AudioLines size={20} />
          <span className={`font-medium ${mobile ? 'block' : 'hidden lg:block'}`}>Transkription</span>
        </button>

        <button
          onClick={() => handleTabSelect('longform')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'longform' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <FileVideo size={20} />
          <span className={`font-medium ${mobile ? 'block' : 'hidden lg:block'}`}>Longform Video Editor</span>
        </button>

        <button
          onClick={() => handleTabSelect('social-upload')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'social-upload' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <Share2 size={20} />
          <span className={`font-medium ${mobile ? 'block' : 'hidden lg:block'}`}>Upload-Post</span>
        </button>

        <button
          onClick={() => handleTabSelect('settings')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${activeTab === 'settings' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'}`}
        >
          <Settings size={20} />
          <span className={`font-medium ${mobile ? 'block' : 'hidden lg:block'}`}>Einstellungen</span>
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
          <div className={`${mobile ? 'block' : 'hidden lg:block'} overflow-hidden`}>
            <p className="text-sm font-bold text-white leading-none mb-0.5">Landingpage</p>
            <p className="text-[10px] text-zinc-400 group-hover:text-zinc-300 transition-colors truncate">Website öffnen</p>
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
          <div className={`${mobile ? 'block' : 'hidden lg:block'} overflow-hidden`}>
            <p className="text-sm font-bold text-white leading-none mb-0.5">Open Source</p>
            <p className="text-[10px] text-zinc-400 group-hover:text-zinc-300 transition-colors truncate">Kostenlos & Community-getrieben</p>
          </div>
        </a>
      </div>
    </div>
  );

  const processingElapsedSeconds = processingStartedAt ? Math.max(0, Math.floor((Date.now() - processingStartedAt) / 1000)) : 0;
  const mobileProcessingProgress = estimateMobileProcessingProgress(logs, status, jobState, processingElapsedSeconds);
  const showMobileProcessingIndicator = status === 'processing' && mobileProcessingProgress.percent < 100;
  const displayLogs = [...logs].reverse();

  return (
    <div className="flex h-[100svh] min-h-[100svh] bg-background overflow-hidden selection:bg-primary/30">
      <aside className="hidden md:flex h-full">
        <Sidebar />
      </aside>

      {isMobileSidebarOpen && (
        <div className="fixed inset-0 z-[140] md:hidden">
          <button
            type="button"
            aria-label="Menü-Overlay schließen"
            className="absolute inset-0 bg-black/70 backdrop-blur-[1px]"
            onClick={() => setIsMobileSidebarOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 pointer-events-none">
            <div className="h-full pointer-events-auto relative">
              <button
                type="button"
                aria-label="Menü schließen"
                onClick={() => setIsMobileSidebarOpen(false)}
                className="absolute top-3 right-3 z-10 inline-flex items-center justify-center w-8 h-8 rounded-lg border border-white/10 bg-black/45 text-zinc-200 hover:text-white hover:bg-black/65 transition-colors"
              >
                <X size={16} />
              </button>
              <Sidebar mobile />
            </div>
          </div>
        </div>
      )}

      <main className="flex-1 min-w-0 flex flex-col h-full min-h-0 overflow-hidden relative">
        {/* Background Gradients */}
        <div className="absolute inset-0 overflow-hidden -z-10 pointer-events-none">
          <div className="absolute -top-[10%] -right-[10%] w-[50%] h-[50%] bg-primary/5 rounded-full blur-[120px]" />
        </div>

        {/* Top Header */}
        <header className="h-16 border-b border-white/5 bg-background/50 backdrop-blur-md flex items-center justify-between px-4 md:px-6 shrink-0 z-10">
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => setIsMobileSidebarOpen(true)}
              className="md:hidden inline-flex items-center justify-center w-9 h-9 rounded-lg border border-white/10 bg-white/5 text-zinc-200 hover:text-white hover:bg-white/10 transition-colors"
              aria-label="Navigationsmenü öffnen"
            >
              <Menu size={18} />
            </button>
            {status !== 'idle' && (
              <button
                onClick={handleReset}
                className="flex items-center gap-2 text-sm text-zinc-400 hover:text-white transition-colors"
              >
                <PlusCircle size={16} />
                <span className="hidden sm:inline">Neues Projekt</span>
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

            {!resolveCurrentProviderStatus().ready && (
              <span className="text-xs text-amber-500 bg-amber-500/10 px-3 py-1 rounded-full border border-amber-500/20">
                {resolveCurrentProviderStatus().label}
              </span>
            )}
          </div>
        </header>

        {/* Main Workspace */}
        <div className="flex-1 min-h-0 overflow-hidden relative">

          {activeTab === 'history' && (
            <JobHistory
              jobs={historyJobs}
              queueOverview={queueOverview}
              loading={historyLoading}
              error={historyError}
              currentJobId={jobId}
              cancelingJobId={cancelingJobId}
              deletingJobId={deletingJobId}
              onRefresh={fetchJobHistory}
              onOpenJob={handleOpenJob}
              onOpenJobWithoutPreviews={handleOpenJobWithoutPreviews}
              onResumeJob={handleResumeJob}
              onReanalyzeJobWithMinimax={handleReanalyzeJobWithMinimax}
              reanalyzingJobId={reanalyzingJobId}
              onCancelJob={handleCancelJob}
              onPauseBulkOperation={handlePauseBulkOperationFromHistory}
              onResumeBulkOperation={handleResumeBulkOperationFromHistory}
              onStopBulkOperation={handleStopBulkOperationFromHistory}
              bulkControlBusy={bulkControlBusy}
              onDeleteJob={handleDeleteJob}
              onOpenGlobalCalendar={loadGlobalCalendar}
              globalCalendarLoading={globalCalendarLoading}
              uploadProfiles={userProfiles}
              activeUploadProfile={uploadUserId}
              onAssignUploadProfile={assignUploadProfileToJob}
              showUnassignedJobs={showUnassignedHistoryJobs}
              onToggleUnassignedJobs={() => setShowUnassignedHistoryJobs((value) => !value)}
            />
          )}

          {activeTab === 'transcription' && (
            <TranscriptionStudio />
          )}

          {activeTab === 'longform' && (
            <LongformVideoEditor
              globalAiDefaults={{
                provider: longformAiDefaults.provider,
                gemini_api_key: apiKey,
                gemini_model: geminiModel,
                huggingface_token: huggingFaceKey,
                openai_api_key: openaiKey,
                openai_model: openaiModel,
                claude_api_key: claudeKey,
                claude_model: claudeModel,
                minimax_api_key: minimaxKey,
                minimax_auth_mode: minimaxAuthMode,
                minimax_model: minimaxModel,
                midjourney_api_key: midjourneyKey,
                midjourney_base_url: midjourneyBaseUrl,
                ollama_base_url: longformAiDefaults.ollama_base_url,
                ollama_model: longformAiDefaults.ollama_model,
              }}
              thumbnailPromptPresets={longformThumbnailPromptPresets}
              thumbnailModelDefaults={longformThumbnailModelDefaults}
              onSaveAiDefaults={(nextDefaults) => setLongformAiDefaults(normalizeLongformAiDefaults(nextDefaults))}
            />
          )}

          {/* View: Settings */}
          {activeTab === 'settings' && (
            <div className="h-full overflow-y-auto touch-scroll p-5 md:p-8 max-w-2xl mx-auto animate-[fadeIn_0.3s_ease-out]">
              <div className="flex items-center justify-between mb-8">
                <h1 className="text-2xl font-bold">Einstellungen</h1>
                <div className="px-3 py-1 bg-green-500/10 border border-green-500/20 rounded-full text-[10px] text-green-400 font-medium flex items-center gap-2">
                  <Shield size={12} /> Datenschutz: Keys bleiben im Browser (werden nur zur Verarbeitung ans Backend gesendet)
                </div>
              </div>
              <div className="glass-panel p-6 mb-8">
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2 bg-white/5 rounded-lg text-zinc-200">
                    <Sparkles size={18} />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold">AI Zugriff & Provider</h2>
                    <p className="text-xs text-zinc-500 mt-1">Hier verwalten wir die globalen Shortform-/Longform-Zugänge. Der aktive Shortform-Provider steuert die Clip-Auswahl und hook-getriebene Generierung.</p>
                  </div>
                </div>

                <div className="mb-5">
                  <label className="block text-sm text-zinc-400 mb-3">Shortform-Provider</label>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                    {SHORTFORM_PROVIDER_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setLlmProvider(option.value)}
                        className={`rounded-xl border px-4 py-3 text-sm text-left transition-colors ${llmProvider === option.value ? 'border-primary bg-primary/10 text-white' : 'border-white/10 text-zinc-400 hover:bg-white/5'}`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="rounded-2xl border border-white/10 bg-black/20 p-4 mb-5 space-y-4">
                  <div>
                    <div className="text-sm font-semibold text-white">
                      Aktiver Shortform-Provider: {SHORTFORM_PROVIDER_OPTIONS.find((option) => option.value === llmProvider)?.label || llmProvider}
                    </div>
                    <div className="mt-1 text-xs text-zinc-500">
                      Dieses Setup wird für Shorts-Analyse, Hook-Generierung und rendernahe AI-Schritte als Default verwendet.
                    </div>
                  </div>

                  {llmProvider === 'gemini' && (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Gemini API-Key</label>
                        <input
                          type="password"
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          placeholder="AIzaSy..."
                          className="input-field w-full font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Gemini Modell</label>
                        <input
                          type="text"
                          list="shortform-gemini-models"
                          value={geminiModel}
                          onChange={(e) => setGeminiModel(normalizeShortformModel('gemini', e.target.value))}
                          className="input-field w-full font-mono"
                        />
                        <datalist id="shortform-gemini-models">
                          {SHORTFORM_MODEL_SUGGESTIONS.gemini.map((model) => <option key={model} value={model} />)}
                        </datalist>
                      </div>
                    </div>
                  )}

                  {llmProvider === 'openai' && (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">OpenAI API-Key</label>
                        <input
                          type="password"
                          value={openaiKey}
                          onChange={(e) => setOpenaiKey(e.target.value)}
                          placeholder="sk-..."
                          className="input-field w-full font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">OpenAI Modell</label>
                        <input
                          type="text"
                          list="shortform-openai-models"
                          value={openaiModel}
                          onChange={(e) => setOpenaiModel(normalizeShortformModel('openai', e.target.value))}
                          className="input-field w-full font-mono"
                        />
                        <datalist id="shortform-openai-models">
                          {SHORTFORM_MODEL_SUGGESTIONS.openai.map((model) => <option key={model} value={model} />)}
                        </datalist>
                      </div>
                    </div>
                  )}

                  {llmProvider === 'claude' && (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Claude API-Key</label>
                        <input
                          type="password"
                          value={claudeKey}
                          onChange={(e) => setClaudeKey(e.target.value)}
                          placeholder="sk-ant-..."
                          className="input-field w-full font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Claude Modell</label>
                        <input
                          type="text"
                          list="shortform-claude-models"
                          value={claudeModel}
                          onChange={(e) => setClaudeModel(normalizeShortformModel('claude', e.target.value))}
                          className="input-field w-full font-mono"
                        />
                        <datalist id="shortform-claude-models">
                          {SHORTFORM_MODEL_SUGGESTIONS.claude.map((model) => <option key={model} value={model} />)}
                        </datalist>
                      </div>
                    </div>
                  )}

                  {llmProvider === 'minimax' && (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">MiniMax-Zugangsmodus</label>
                        <select
                          value={minimaxAuthMode}
                          onChange={(e) => setMinimaxAuthMode(e.target.value)}
                          className="input-field w-full"
                        >
                          {MINIMAX_AUTH_MODE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
                        </select>
                        <p className="mt-2 text-xs text-zinc-500">
                          {MINIMAX_AUTH_MODE_OPTIONS.find((option) => option.value === minimaxAuthMode)?.description}
                        </p>
                      </div>
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">MiniMax Modell</label>
                        <input
                          type="text"
                          list="shortform-minimax-models"
                          value={minimaxModel}
                          onChange={(e) => setMinimaxModel(normalizeShortformModel('minimax', e.target.value))}
                          className="input-field w-full font-mono"
                        />
                        <datalist id="shortform-minimax-models">
                          {SHORTFORM_MODEL_SUGGESTIONS.minimax.map((model) => <option key={model} value={model} />)}
                        </datalist>
                      </div>
                      <div className="md:col-span-2">
                        <label className="block text-sm text-zinc-400 mb-2">
                          {minimaxAuthMode === 'token_plan' ? 'MiniMax Token Plan Key' : 'MiniMax Pay-as-you-go API-Key'}
                        </label>
                        <input
                          type="password"
                          value={minimaxKey}
                          onChange={(e) => setMinimaxKey(e.target.value)}
                          placeholder={minimaxAuthMode === 'token_plan' ? 'Token Plan Key' : 'Open Platform API Key'}
                          className="input-field w-full font-mono"
                        />
                        <p className="mt-2 text-xs text-zinc-500">
                          {minimaxAuthMode === 'token_plan'
                            ? 'Nutze hier den separaten Token-Plan-Key aus deinem MiniMax-Token-Plan. Dieser Key ist laut MiniMax nicht identisch mit dem normalen API-Key.'
                            : 'Nutze hier den normalen Open-Platform-API-Key fuer verbrauchsbasierte Abrechnung.'}
                        </p>
                      </div>
                    </div>
                  )}

                  {llmProvider === 'ollama' && (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Ollama Base-URL</label>
                        <input
                          type="text"
                          value={ollamaBaseUrl}
                          onChange={(e) => setOllamaBaseUrl(e.target.value)}
                          placeholder="http://127.0.0.1:11434"
                          className="input-field w-full font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Ollama Modell</label>
                        <input
                          type="text"
                          list="shortform-ollama-models"
                          value={ollamaModel}
                          onChange={(e) => setOllamaModel(e.target.value)}
                          className="input-field w-full font-mono"
                        />
                        <datalist id="shortform-ollama-models">
                          {SHORTFORM_MODEL_SUGGESTIONS.ollama.map((model) => <option key={model} value={model} />)}
                        </datalist>
                      </div>
                    </div>
                  )}
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Hugging Face / pyannote Token</label>
                    <input
                      type="password"
                      value={huggingFaceKey}
                      onChange={(e) => setHuggingFaceKey(e.target.value)}
                      placeholder="hf_..."
                      className="input-field w-full font-mono"
                    />
                    <p className="mt-2 text-xs text-zinc-500">Wird fuer pyannote Speaker Diarization in Longform verwendet, wenn der Toggle aktiviert ist.</p>
                  </div>
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Midjourney Bridge API-Key</label>
                    <input
                      type="password"
                      value={midjourneyKey}
                      onChange={(e) => setMidjourneyKey(e.target.value)}
                      placeholder="Optionaler Bearer-Key"
                      className="input-field w-full font-mono"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="block text-sm text-zinc-400 mb-2">Midjourney Bridge URL</label>
                    <input
                      type="text"
                      value={midjourneyBaseUrl}
                      onChange={(e) => setMidjourneyBaseUrl(e.target.value)}
                      placeholder="z.B. https://dein-bridge-service.example.com/v1/generate"
                      className="input-field w-full font-mono"
                    />
                    <p className="mt-2 text-xs text-zinc-500">
                      Midjourney ist hier als Bridge-Provider angebunden. OpenShorts sendet Prompt, Modell, Variantenanzahl und Referenzbilder an diese URL und erwartet Bilddaten oder URLs zurueck.
                    </p>
                  </div>
                </div>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2 bg-white/5 rounded-lg text-zinc-200">
                    <Image size={18} />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold">Thumbnail-Modell-Defaults</h2>
                    <p className="text-xs text-zinc-500 mt-1">Diese Default-Modelle werden im Longform-Thumbnail-Flow vorbefuellt. Im Job selbst kannst du sie pro Provider noch ueberschreiben.</p>
                  </div>
                </div>
                <div className="space-y-4">
                  {Object.entries(THUMBNAIL_MODEL_SUGGESTIONS).map(([provider, suggestions]) => (
                    <div key={provider} className="rounded-2xl border border-white/10 bg-black/20 p-4">
                      <div className="flex items-center justify-between gap-3 mb-3">
                        <div>
                          <div className="font-medium text-white capitalize">{provider}</div>
                          <div className="text-xs text-zinc-500">
                            {provider === 'gemini' && 'Gemini-Bildmodelle laut aktueller Google-Doku.'}
                            {provider === 'openai' && 'OpenAI-Bildmodell fuer Generations-/Edit-Flow.'}
                            {provider === 'midjourney' && 'Bridge-spezifischer Modellname oder Alias. Freitext ist erlaubt.'}
                          </div>
                        </div>
                        <input
                          type="text"
                          value={longformThumbnailModelDefaults[provider] || ''}
                          onChange={(e) => setLongformThumbnailModelDefaults((prev) => ({ ...prev, [provider]: e.target.value }))}
                          placeholder="Eigenes Modell eingeben"
                          className="input-field w-full max-w-md font-mono"
                        />
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {suggestions.map((modelName) => (
                          <button
                            key={modelName}
                            type="button"
                            onClick={() => setLongformThumbnailModelDefaults((prev) => ({ ...prev, [provider]: modelName }))}
                            className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                              (longformThumbnailModelDefaults[provider] || '') === modelName
                                ? 'border-primary/50 bg-primary/20 text-white'
                                : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'
                            }`}
                          >
                            {modelName}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2 bg-white/5 rounded-lg text-zinc-200">
                    <Image size={18} />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold">Longform Thumbnail-Prompts</h2>
                    <p className="text-xs text-zinc-500 mt-1">Benannte Presets fuer den Longform-Thumbnail-Flow. Sie stehen in jedem Longform-Job zur Auswahl und koennen dort noch frei angepasst werden.</p>
                  </div>
                </div>
                <div className="space-y-4">
                  {longformThumbnailPromptPresets.map((preset, index) => (
                    <div key={preset.id || index} className="rounded-2xl border border-white/10 bg-black/20 p-4 space-y-3">
                      <div className="grid gap-3 sm:grid-cols-[220px_1fr_auto]">
                        <input
                          value={preset.name}
                          onChange={(e) => setLongformThumbnailPromptPresets((prev) => prev.map((item, itemIndex) => (
                            itemIndex === index ? { ...item, name: e.target.value } : item
                          )))}
                          className="input-field"
                          placeholder="Preset-Name"
                        />
                        <input
                          value={preset.id}
                          onChange={(e) => setLongformThumbnailPromptPresets((prev) => prev.map((item, itemIndex) => (
                            itemIndex === index ? { ...item, id: e.target.value } : item
                          )))}
                          className="input-field font-mono"
                          placeholder="preset_id"
                        />
                        <button
                          type="button"
                          onClick={() => setLongformThumbnailPromptPresets((prev) => prev.filter((_, itemIndex) => itemIndex !== index))}
                          className="rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-200 hover:bg-red-500/20"
                        >
                          Entfernen
                        </button>
                      </div>
                      <textarea
                        value={preset.prompt}
                        onChange={(e) => setLongformThumbnailPromptPresets((prev) => prev.map((item, itemIndex) => (
                          itemIndex === index ? { ...item, prompt: e.target.value } : item
                        )))}
                        rows={4}
                        className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-primary/50"
                        placeholder="Beschreibe hier den gewuenschten Thumbnail-Stil..."
                      />
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() => setLongformThumbnailPromptPresets((prev) => [
                      ...prev,
                      {
                        id: `preset_${prev.length + 1}`,
                        name: `Preset ${prev.length + 1}`,
                        prompt: '',
                      },
                    ])}
                    className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white hover:bg-white/10"
                  >
                    Neues Preset
                  </button>
                </div>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2 bg-accent/20 rounded-lg text-accent">
                    <Image size={18} />
                  </div>
                  <h2 className="text-lg font-semibold">Pexels API-Key</h2>
                </div>
                <div className="relative">
                  <input
                    type="password"
                    value={pexelsKey}
                    onChange={(e) => setPexelsKey(e.target.value)}
                    placeholder="Pexels API-Key"
                    className="input-field w-full font-mono"
                  />
                </div>
                <p className="mt-3 text-xs text-zinc-500">
                  Optional: Der Pexels-Key wird für AI-gesteuerte Stock-Image-Overlays im viralen Render verwendet.
                </p>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">YouTube-Downloadqualität</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Lokales Setup</span>
                </div>
                <div className="space-y-4">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Auth-Modus</label>
                      <select
                        value={youtubeAuthSettings.mode}
                        onChange={(e) => setYoutubeAuthSettings((prev) => ({ ...prev, mode: e.target.value }))}
                        className="input-field"
                      >
                        {YOUTUBE_AUTH_MODE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Browser (für Browser-Modus)</label>
                      <select
                        value={youtubeAuthSettings.browser}
                        onChange={(e) => setYoutubeAuthSettings((prev) => ({ ...prev, browser: e.target.value }))}
                        className="input-field"
                      >
                        {YOUTUBE_BROWSER_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">cookies.txt (Netscape-Format, optional)</label>
                    <textarea
                      value={youtubeAuthSettings.cookiesText}
                      onChange={(e) => setYoutubeAuthSettings((prev) => ({ ...prev, cookiesText: e.target.value }))}
                      rows={5}
                      className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-primary/50 font-mono resize-y"
                      placeholder="# Netscape HTTP Cookie File ..."
                    />
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={saveYoutubeCookiesToBackend}
                      disabled={youtubeAuthBusy}
                      className="px-3 py-1.5 rounded-lg bg-primary/20 border border-primary/30 text-xs text-primary hover:bg-primary/30 disabled:opacity-50"
                    >
                      Cookies speichern (Backend)
                    </button>
                    <button
                      type="button"
                      onClick={importYoutubeCookiesFromBrowser}
                      disabled={youtubeAuthBusy}
                      className="px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                    >
                      Browser-Login importieren
                    </button>
                    <button
                      type="button"
                      onClick={refreshYoutubeAuthStatus}
                      disabled={youtubeAuthBusy}
                      className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-zinc-200 hover:bg-white/10 disabled:opacity-50"
                    >
                      Status pruefen
                    </button>
                    <button
                      type="button"
                      onClick={deleteYoutubeCookiesFromBackend}
                      disabled={youtubeAuthBusy}
                      className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-300 hover:bg-red-500/20 disabled:opacity-50"
                    >
                      Cookies loeschen
                    </button>
                    <span className={`ml-auto text-[11px] px-2 py-1 rounded border ${youtubeAuthStatus?.logged_in ? 'bg-green-500/10 border-green-500/20 text-green-300' : 'bg-zinc-500/10 border-zinc-500/20 text-zinc-300'}`}>
                      {youtubeAuthStatus?.logged_in ? 'Login erkannt' : 'Nicht eingeloggt'}
                    </span>
                  </div>

                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Bei jedem Job werden diese Einstellungen an den Downloader uebergeben. Wenn YouTube nur niedrige Qualitaet anbietet, bricht der Job jetzt sauber ab statt 360p weiterzuverarbeiten.
                    Für gesperrte Streams sind frische Login-Cookies meist Pflicht.
                  </p>
                  {youtubeAuthStatus?.cookies_file_path && (
                    <p className="text-[11px] text-zinc-600 break-all">
                      cookies file: {youtubeAuthStatus.cookies_file_path} ({youtubeAuthStatus.cookies_file_size || 0} bytes)
                    </p>
                  )}
                  <p className="text-[11px] text-zinc-600 leading-relaxed">
                    Hinweis: Der Browser-Import liest Cookies vom Host-Rechner, auf dem Docker läuft. Auf iPhone/iPad kann Safari-Cookie-Export nicht direkt automatisiert ausgelesen werden.
                  </p>
                </div>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Geräte-Sync</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Cloud + Datei</span>
                </div>
                <div className="space-y-4">
                  <label className="flex items-start gap-3 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-left">
                    <input
                      type="checkbox"
                      checked={settingsSyncIncludeYoutubeCookies}
                      onChange={(e) => setSettingsSyncIncludeYoutubeCookies(e.target.checked)}
                      className="mt-1 h-4 w-4 rounded border-white/20 bg-transparent text-primary focus:ring-primary"
                    />
                    <span>
                      <span className="block text-sm font-medium text-white">YouTube Session mit synchronisieren</span>
                      <span className="block text-xs text-zinc-500">
                        Wenn aktiv, wird die aktuelle Backend-YouTube-Session im Sync-Profil hinterlegt und beim Laden auf einem anderen Gerät wiederhergestellt.
                      </span>
                    </span>
                  </label>

                  <div className="rounded-xl border border-amber-400/20 bg-amber-400/5 px-4 py-4">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-sm font-medium text-white">Einstellungen auf einen anderen Rechner umziehen</p>
                        <p className="mt-1 text-xs leading-relaxed text-zinc-400">
                          Exportiert API-Schlüssel, Anbieter-, Upload-, Relay- und Design-Einstellungen. Projekte, Jobs, Videos und Renderdaten werden nie mit exportiert.
                        </p>
                        <p className="mt-2 text-[11px] leading-relaxed text-amber-200/80">
                          Sicherheitswarnung: Die JSON-Datei enthält Geheimnisse im Klartext. Nach dem Import sicher löschen und nicht in Git ablegen.
                        </p>
                      </div>
                      <div className="flex shrink-0 flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={exportSettingsToFile}
                          disabled={settingsSyncBusy}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300/30 bg-amber-300/10 px-3 py-1.5 text-xs text-amber-100 hover:bg-amber-300/20 disabled:opacity-50"
                        >
                          <Download size={14} /> Einstellungen exportieren
                        </button>
                        <button
                          type="button"
                          onClick={() => settingsImportInputRef.current?.click()}
                          disabled={settingsSyncBusy}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-200 hover:bg-white/10 disabled:opacity-50"
                        >
                          <Upload size={14} /> Einstellungen importieren
                        </button>
                        <input
                          ref={settingsImportInputRef}
                          type="file"
                          accept="application/json,.json"
                          onChange={importSettingsFromFile}
                          className="hidden"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={createSettingsSyncCode}
                      disabled={settingsSyncBusy}
                      className="px-3 py-1.5 rounded-lg bg-primary/20 border border-primary/30 text-xs text-primary hover:bg-primary/30 disabled:opacity-50"
                    >
                      Sync-Key erstellen
                    </button>
                    <button
                      type="button"
                      onClick={loadSettingsFromSyncCode}
                      disabled={settingsSyncBusy}
                      className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-zinc-200 hover:bg-white/10 disabled:opacity-50"
                    >
                      Vom Sync-Key laden
                    </button>
                    {generatedSettingsSyncCode && (
                      <button
                        type="button"
                        onClick={() => navigator.clipboard?.writeText(generatedSettingsSyncCode)}
                        className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-zinc-300 hover:bg-white/10"
                      >
                        Key kopieren
                      </button>
                    )}
                  </div>

                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Sync-Key</label>
                    <textarea
                      value={settingsSyncCode}
                      onChange={(e) => setSettingsSyncCode(e.target.value)}
                      rows={3}
                      className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-primary/50 font-mono resize-y"
                      placeholder="xxxxxx.yyyyyyyyyyyyyyyyyyyyyyyyyyy"
                    />
                  </div>

                  {settingsSyncStatus?.message && (
                    <p className={`text-xs ${settingsSyncStatus.type === 'error' ? 'text-red-300' : 'text-emerald-300'}`}>
                      {settingsSyncStatus.message}
                    </p>
                  )}
                </div>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Overlay-Profile</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Global</span>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Aktives Profil</label>
                    <select
                      value={activeOverlayProfileId}
                      onChange={(e) => setActiveOverlayProfileId(e.target.value)}
                      className="input-field"
                    >
                      {Object.values(overlayProfiles).map((profile) => (
                        <option key={profile.id} value={profile.id}>
                          {profile.name}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs text-zinc-500 mt-2">
                      Bei aktivem <strong>Interview-Modus</strong> im Formular wird automatisch das Profil <strong>Interview</strong> als Job-Standard verwendet.
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={applyCurrentStylesToActiveOverlayProfile}
                      className="px-3 py-1.5 rounded-lg bg-primary/20 border border-primary/30 text-xs text-primary hover:bg-primary/30"
                    >
                      Aktuelles Profil überschreiben
                    </button>
                  </div>

                  <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Als neues Profil speichern</label>
                      <input
                        type="text"
                        value={overlayProfileNameDraft}
                        onChange={(e) => setOverlayProfileNameDraft(e.target.value)}
                        className="input-field"
                        placeholder="z.B. Cinematic, Faceless, News"
                      />
                    </div>
                    <button
                      type="button"
                      onClick={saveCurrentStylesAsNewOverlayProfile}
                      className="px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-zinc-200 hover:bg-white/10"
                    >
                      Profil speichern
                    </button>
                  </div>

                  {overlayProfileStatus?.message && (
                    <p className={`text-xs ${overlayProfileStatus.type === 'error' ? 'text-red-300' : 'text-emerald-300'}`}>
                      {overlayProfileStatus.message}
                    </p>
                  )}
                </div>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Untertitel-Defaults</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Global</span>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Schnellposition</label>
                    <div className="grid grid-cols-3 gap-2">
                      {SUBTITLE_POSITION_PRESETS.map((preset) => (
                        <button
                          key={preset.value}
                          type="button"
                          onClick={() => setSubtitleStyle((prev) => ({
                            ...prev,
                            position: preset.value,
                            yPosition: preset.y,
                          }))}
                          className={`rounded-lg border px-3 py-2 text-xs font-semibold transition-colors ${Math.abs((subtitleStyle.yPosition ?? SUBTITLE_POSITION_PRESETS[2].y) - preset.y) < 1
                            ? 'border-primary/50 bg-primary/20 text-white'
                            : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'
                            }`}
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Y-Position</label>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={subtitleStyle.yPosition ?? SUBTITLE_POSITION_PRESETS[2].y}
                      onChange={(e) => {
                        const nextY = Number(e.target.value);
                        setSubtitleStyle((prev) => ({
                          ...prev,
                          yPosition: nextY,
                          position: resolveSubtitlePositionFromY(nextY),
                        }));
                      }}
                      className="w-full accent-yellow-500"
                    />
                    <div className="mt-2 flex justify-between text-xs text-zinc-500">
                      <span>Oben</span>
                      <span>{Math.round(subtitleStyle.yPosition ?? SUBTITLE_POSITION_PRESETS[2].y)}%</span>
                      <span>Unten</span>
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Schriftart</label>
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
                      <label className="block text-sm text-zinc-400 mb-2">Hintergrund</label>
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

                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Schriftgröße</label>
                    <input
                      type="range"
                      min="18"
                      max="44"
                      step="1"
                      value={subtitleStyle.fontSize ?? DEFAULT_SUBTITLE_STYLE.fontSize}
                      onChange={(e) => setSubtitleStyle((prev) => ({ ...prev, fontSize: Number(e.target.value) }))}
                      className="w-full accent-yellow-500"
                    />
                    <div className="mt-2 text-xs text-zinc-500">
                      {subtitleStyle.fontSize ?? DEFAULT_SUBTITLE_STYLE.fontSize}px
                    </div>
                  </div>
                </div>
                <p className="text-xs text-zinc-500 mt-4">
                  Diese Defaults befüllen den Untertitel-Dialog pro Short vor und können dort weiter angepasst werden.
                </p>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Hook-Vorgaben</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Global</span>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Schnell-Presets</label>
                    <div className="grid grid-cols-3 gap-2">
                      {GRID_OPTIONS.map((option) => {
                        const coords = resolveHookGridToCoordinates(option.value);
                        const activeGridValue = resolveHookGridFromCoordinates(
                          hookStyle.xPosition ?? DEFAULT_HOOK_STYLE.xPosition,
                          hookStyle.yPosition ?? DEFAULT_HOOK_STYLE.yPosition
                        );
                        const isActive = activeGridValue === option.value;
                        return (
                          <button
                            key={option.value}
                            type="button"
                            onClick={() => setHookStyle((prev) => ({
                              ...prev,
                              xPosition: coords.x,
                              yPosition: coords.y,
                              position: coords.position,
                              horizontalPosition: coords.horizontalPosition,
                              textAlign: coords.textAlign,
                            }))}
                            className={`rounded-lg border px-2 py-2 text-[11px] font-semibold transition-colors ${isActive
                              ? 'border-yellow-300/50 bg-yellow-500/20 text-white'
                              : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'
                              }`}
                          >
                            {option.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">X-Position</label>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        step="1"
                        value={hookStyle.xPosition ?? DEFAULT_HOOK_STYLE.xPosition}
                        onChange={(e) => {
                          const nextX = Number(e.target.value);
                          setHookStyle((prev) => ({
                            ...prev,
                            xPosition: nextX,
                            horizontalPosition: nextX < 34 ? 'left' : nextX > 66 ? 'right' : 'center',
                          }));
                        }}
                        className="w-full accent-yellow-500"
                      />
                      <div className="mt-2 flex justify-between text-xs text-zinc-500">
                        <span>Links</span>
                        <span>{Math.round(hookStyle.xPosition ?? DEFAULT_HOOK_STYLE.xPosition)}%</span>
                        <span>Rechts</span>
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Y-Position</label>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        step="1"
                        value={hookStyle.yPosition ?? DEFAULT_HOOK_STYLE.yPosition}
                        onChange={(e) => {
                          const nextY = Number(e.target.value);
                          setHookStyle((prev) => ({
                            ...prev,
                            yPosition: nextY,
                            position: nextY < 34 ? 'top' : nextY > 66 ? 'bottom' : 'center',
                          }));
                        }}
                        className="w-full accent-yellow-500"
                      />
                      <div className="mt-2 flex justify-between text-xs text-zinc-500">
                        <span>Oben</span>
                        <span>{Math.round(hookStyle.yPosition ?? DEFAULT_HOOK_STYLE.yPosition)}%</span>
                        <span>Unten</span>
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Textausrichtung</label>
                      <div className="grid grid-cols-3 gap-2">
                        {HOOK_TEXT_ALIGN_OPTIONS.map((option) => (
                          <button
                            key={option.value}
                            type="button"
                            onClick={() => setHookStyle((prev) => ({
                              ...prev,
                              textAlign: option.value,
                              horizontalPosition: option.value,
                            }))}
                            className={`rounded-lg border px-2 py-2 text-xs font-semibold transition-colors ${ (hookStyle.textAlign || DEFAULT_HOOK_STYLE.textAlign) === option.value
                              ? 'border-yellow-300/50 bg-yellow-500/20 text-white'
                              : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'
                              }`}
                          >
                            {option.label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Größe</label>
                      <div className="grid grid-cols-3 gap-2">
                        {HOOK_SIZE_OPTIONS.map((option) => (
                          <button
                            key={option.value}
                            type="button"
                            onClick={() => setHookStyle((prev) => ({ ...prev, size: option.value }))}
                            className={`rounded-lg border px-2 py-2 text-xs font-semibold transition-colors ${ (hookStyle.size || DEFAULT_HOOK_STYLE.size) === option.value
                              ? 'border-yellow-300/50 bg-yellow-500/20 text-white'
                              : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'
                              }`}
                          >
                            {option.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Breite</label>
                      <select
                        value={hookStyle.widthPreset || DEFAULT_HOOK_STYLE.widthPreset}
                        onChange={(e) => setHookStyle((prev) => ({ ...prev, widthPreset: e.target.value }))}
                        className="input-field"
                      >
                        {HOOK_WIDTH_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Schriftart</label>
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
                  </div>

                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Hintergrund</label>
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

                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Start-Zoom</label>
                    <input
                      type="range"
                      min="0"
                      max="2"
                      step="0.05"
                      value={hookStyle.startZoomFactor ?? DEFAULT_HOOK_STYLE.startZoomFactor}
                      onChange={(e) => setHookStyle((prev) => {
                        const nextStart = clampZoomFactor(e.target.value, DEFAULT_HOOK_STYLE.startZoomFactor);
                        const currentMax = clampZoomFactor(prev.zoomFactor ?? DEFAULT_HOOK_STYLE.zoomFactor, DEFAULT_HOOK_STYLE.zoomFactor);
                        return {
                          ...prev,
                          startZoomFactor: Math.min(nextStart, currentMax),
                        };
                      })}
                      className="w-full accent-cyan-500"
                    />
                    <div className="mt-2 flex justify-between text-xs text-zinc-500">
                      <span>0.00x</span>
                      <span>{(hookStyle.startZoomFactor ?? DEFAULT_HOOK_STYLE.startZoomFactor).toFixed(2)}x</span>
                      <span>2.00x</span>
                    </div>
                    <p className="mt-2 text-xs text-zinc-500">
                      Legt fest, auf welchem Gesichts-Zoom-Level der Clip grundsätzlich startet.
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Ziel-Zoom</label>
                    <input
                      type="range"
                      min="0"
                      max="2"
                      step="0.05"
                      value={hookStyle.zoomFactor ?? DEFAULT_HOOK_STYLE.zoomFactor}
                      onChange={(e) => setHookStyle((prev) => {
                        const nextMax = clampZoomFactor(e.target.value, DEFAULT_HOOK_STYLE.zoomFactor);
                        const currentStart = clampZoomFactor(prev.startZoomFactor ?? DEFAULT_HOOK_STYLE.startZoomFactor, DEFAULT_HOOK_STYLE.startZoomFactor);
                        return {
                          ...prev,
                          zoomFactor: Math.max(nextMax, currentStart),
                        };
                      })}
                      className="w-full accent-yellow-500"
                    />
                    <div className="mt-2 flex justify-between text-xs text-zinc-500">
                      <span>0.00x</span>
                      <span>{(hookStyle.zoomFactor ?? DEFAULT_HOOK_STYLE.zoomFactor).toFixed(2)}x</span>
                      <span>2.00x</span>
                    </div>
                    <p className="mt-2 text-xs text-zinc-500">
                      Definiert den echten Peak der Viral-Zooms. Jeder Clip startet mit einem schnellen smoothen Einstiegs-Zoom und bekommt danach wiederholte In/Out-Pulse.
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Flash-Pattern-Interrupts</label>
                    <select
                      value={hookStyle.flashMode || DEFAULT_HOOK_STYLE.flashMode}
                      onChange={(e) => setHookStyle((prev) => ({
                        ...prev,
                        flashMode: normalizePatternFlashMode(e.target.value, DEFAULT_HOOK_STYLE.flashMode),
                      }))}
                      className="input-field"
                    >
                      {PATTERN_FLASH_MODE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                    <p className="mt-2 text-xs text-zinc-500">
                      Steuert nur die hellen Flash-Blitze beim Final-Render. Zoom-Pulse bleiben separat ueber Start-/Ziel-Zoom geregelt.
                    </p>
                  </div>
                </div>
                <p className="text-xs text-zinc-500 mt-4">
                  Diese Vorgaben befüllen den Hook-Dialog pro Short vor und können pro Clip überschrieben werden.
                </p>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Sprachstraffung</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Global</span>
                </div>
                <p className="text-xs text-zinc-500 mb-4 leading-relaxed">
                  Generierte Shorts können lange Sprechpausen und einfache Füllwörter automatisch schneiden, z.B.
                  <strong> äh</strong>, <strong> ähm</strong>, <strong> um</strong> or <strong> uh</strong>.
                  Die Standardeinstellung ist bewusst aggressiv für Kurzformat-Rhythmus.
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
                  <h2 className="text-lg font-semibold">Social-Integration</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Optional</span>
                </div>
                <p className="text-xs text-zinc-500 mb-6 leading-relaxed">
                  Veröffentliche deine Clips automatisch auf TikTok, Instagram Reels, YouTube Shorts, Facebook, X, Threads und Pinterest via <strong>Upload-Post</strong>.
                  Enthält einen <strong>Free-Tier</strong> (keine Kreditkarte nötig).
                  Wenn du willst, kannst du das überspringen und Videos manuell herunterladen/hochladen.
                </p>
                <div className="space-y-4">
                  <label className="block text-sm text-zinc-400">Upload-Post API-Key</label>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={uploadPostKey}
                      onChange={(e) => setUploadPostKey(e.target.value)}
                      className="input-field"
                      placeholder="ey..."
                    />
                    <button onClick={fetchUserProfiles} className="btn-primary py-2 px-4 text-sm">
                      Verbinden
                    </button>
                  </div>
                  {uploadProfileStatus?.message && (
                    <p className={`text-xs mt-2 ${
                      uploadProfileStatus.type === 'success'
                        ? 'text-emerald-300'
                        : uploadProfileStatus.type === 'info'
                          ? 'text-zinc-400'
                          : 'text-red-300'
                    }`}>
                      {uploadProfileStatus.message}
                    </p>
                  )}
                  <div>
                    <label className="block text-sm text-zinc-400 mb-2">Standard Upload-Post-Profil</label>
                    <select
                      value={uploadUserId}
                      onChange={(e) => setUploadUserId(e.target.value)}
                      className="input-field"
                      disabled={userProfiles.length === 0}
                    >
                      <option value="">{userProfiles.length === 0 ? 'Profile zuerst laden' : 'Profil wählen'}</option>
                      {userProfiles.map((profile) => (
                        <option key={profile.username} value={profile.username}>{profile.username}</option>
                      ))}
                    </select>
                    <p className="text-xs text-zinc-500 mt-2">
                      Das ist das globale Upload-Post-Profil für Veröffentlichungen. In einzelnen Clip-Dialogen wird nur das aktive Profil angezeigt.
                    </p>
                    <label className="mt-4 mb-2 block text-sm text-zinc-400">Kanalbeschreibung fuer dieses Profil</label>
                    <textarea
                      value={uploadProfileContexts[uploadUserId] || ''}
                      onChange={(event) => setUploadProfileContexts((previous) => ({
                        ...previous,
                        [uploadUserId]: event.target.value,
                      }))}
                      disabled={!uploadUserId}
                      rows={5}
                      className="input-field resize-y disabled:opacity-50"
                      placeholder="Zielgruppe, Themen, Tonalitaet, Kanalziele und redaktionelle Schwerpunkte. Diese Angaben fliessen in Zusammenfassung, Clipauswahl, Titel, Beschreibung und Hooks ein."
                    />
                  </div>
                  <div className="border border-cyan-500/15 rounded-xl p-4 space-y-4 bg-cyan-500/5">
                    <div>
                      <h3 className="text-sm font-semibold text-cyan-100">Podcast-Link per Kommentar-DM</h3>
                      <p className="mt-1 text-xs text-cyan-100/70">
                        Optionales PHP-Relay auf deinem Netcup-Server. OpenShorts registriert neue Upload-Post-Slots dort; dein Cronjob beantwortet passende Kommentare.
                      </p>
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">PHP-Script-URL</label>
                        <input
                          type="url"
                          value={podcastDmSettings.relayUrl}
                          onChange={(e) => setPodcastDmSettings((prev) => ({ ...prev, relayUrl: e.target.value }))}
                          className="input-field"
                          placeholder="https://deinserver.de/uploadpost_podcast_dm_relay.php"
                        />
                      </div>
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Relay-Passwort</label>
                        <input
                          type="password"
                          value={podcastDmSettings.relayPassword}
                          onChange={(e) => setPodcastDmSettings((prev) => ({ ...prev, relayPassword: e.target.value }))}
                          className="input-field"
                          placeholder="Simple Secret"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Standard-Keyword</label>
                      <input
                        type="text"
                        value={podcastDmSettings.defaultKeyword}
                        onChange={(e) => setPodcastDmSettings((prev) => ({ ...prev, defaultKeyword: e.target.value || 'Video' }))}
                        className="input-field"
                        placeholder="Video"
                      />
                      <p className="mt-2 text-xs text-zinc-500">
                        Instagram-CTA, wenn im Job aktiv: Kommentiere &quot;&lt;Keyword&gt;&quot; und wir senden dir den Link zum Podcast zu.
                      </p>
                    </div>
                  </div>
                  <div className="border border-white/5 rounded-xl p-4 space-y-4 bg-black/10">
                    <div>
                      <label className="block text-sm text-zinc-400 mb-2">Standardmäßig aktive Plattformen</label>
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
                        <label className="block text-sm text-zinc-400 mb-2">Standard-Instagram-Modus</label>
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
                        <label className="block text-sm text-zinc-400 mb-2">Standard TikTok-Post-Modus</label>
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
                      TikTok-Uploads standardmäßig als KI-generiert markieren
                    </label>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Standard Facebook-Page-ID</label>
                        <input
                          type="text"
                          value={socialPostSettings.facebookPageId}
                          onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, facebookPageId: e.target.value }))}
                          className="input-field"
                          placeholder="Optional"
                        />
                      </div>
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Standard Pinterest-Board-ID</label>
                        <input
                          type="text"
                          value={socialPostSettings.pinterestBoardId}
                          onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, pinterestBoardId: e.target.value }))}
                          className="input-field"
                          placeholder="Für Pinterest-Posts erforderlich"
                        />
                      </div>
                    </div>
                    <p className="text-xs text-zinc-500 leading-relaxed">
                      Die erkannte Transkript-Sprache wird dort übergeben, wo Upload-Post derzeit Sprachfelder unterstützt. Laut aktueller Doku betrifft das YouTube, nicht TikTok.
                    </p>
                  </div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Verbinde deinen Upload-Post-Account für Publishing mit einem Klick.
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2">
                      <a href="https://app.upload-post.com/login" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">1. Login</span>
                        <span className="text-[10px] text-zinc-600">Account registrieren</span>
                      </a>
                      <a href="https://app.upload-post.com/manage-users" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">2. Profile</span>
                        <span className="text-[10px] text-zinc-600">Anlegen & verbinden</span>
                      </a>
                      <a href="https://app.upload-post.com/api-keys" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">3. API-Key</span>
                        <span className="text-[10px] text-zinc-600">Key erzeugen</span>
                      </a>
                    </div>
                    <br />
                    <span className="text-zinc-600 italic">
                      Keys werden nur im Browser gespeichert. Sie werden nur zur Verarbeitung ans Backend gesendet und nicht serverseitig gespeichert.
                    </span>
                  </p>
                </div>
              </div>

              <div className="glass-panel p-6 mt-8">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Video-Übersetzung</h2>
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Optional</span>
                </div>
                <p className="text-xs text-zinc-500 mb-6 leading-relaxed">
                  Übersetze deine Clips mit <strong>ElevenLabs</strong>-Dubbing in andere Sprachen.
                  Die Sprache wird automatisch übersetzt, während die Voice-Charakteristik erhalten bleibt.
                </p>
                <div className="space-y-4">
                  <label className="block text-sm text-zinc-400">ElevenLabs API-Key</label>
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
                      alert('ElevenLabs API-Key gespeichert!');
                        }
                      }}
                      className="btn-primary py-2 px-4 text-sm"
                    >
                      Speichern
                    </button>
                  </div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Hole deinen API-Key bei ElevenLabs, um Video-Übersetzung zu aktivieren.
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <a href="https://elevenlabs.io/sign-up" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">1. Registrieren</span>
                        <span className="text-[10px] text-zinc-600">Account erstellen</span>
                      </a>
                      <a href="https://elevenlabs.io/app/settings/api-keys" target="_blank" rel="noopener noreferrer" className="p-2 border border-white/5 rounded-lg hover:bg-white/5 transition-colors flex flex-col gap-1">
                        <span className="text-zinc-400 font-medium">2. API-Key</span>
                        <span className="text-[10px] text-zinc-600">Key erzeugen</span>
                      </a>
                    </div>
                    <br />
                    <span className="text-zinc-600 italic">
                      Keys werden nur im Browser gespeichert. Sie werden nur zur Verarbeitung ans Backend gesendet und nicht serverseitig gespeichert.
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

          {activeTab === 'social-upload' && (
            <SocialUploadStudio
              uploadPostKey={uploadPostKey}
              uploadUserId={uploadUserId}
              socialPostSettings={socialPostSettings}
              podcastDmSettings={podcastDmSettings}
            />
          )}

          {/* View: Gallery */}
          {/* {activeTab === 'gallery' && (
            <Gallery />
          )} */}

          {/* View: Dashboard (Idle) */}
          {activeTab === 'dashboard' && status === 'idle' && (
            <div className="h-full overflow-y-auto touch-scroll flex flex-col items-center justify-center p-5 md:p-6 animate-[fadeIn_0.3s_ease-out]">
              <div className="max-w-xl w-full text-center space-y-8">
                <div className="space-y-4">
                  <h1 className="text-4xl md:text-5xl font-black bg-gradient-to-b from-white to-white/60 bg-clip-text text-transparent">
                    Virale Shorts erstellen
                  </h1>
                  <p className="text-zinc-400 text-lg">
                    Füge unten deine Longform-Video-URL oder Datei ein und erzeuge sofort virale Clips mit KI.
                  </p>
                </div>

                <MediaInput
                  onProcess={handleProcess}
                  isProcessing={isQueueSubmitting}
                  resetToken={mediaInputResetToken}
                  submittingLabel="Job wird eingereiht..."
                  helperText="Jobs laufen seriell, solange das Backend laeuft. Du kannst nach dem Einreihen sofort den naechsten Job konfigurieren."
                  activeProfileName={uploadUserId}
                  profileContext={uploadProfileContexts[uploadUserId] || ''}
                />

                {queueSubmitStatus?.message && (
                  <div className={`rounded-2xl border px-4 py-3 text-sm ${
                    queueSubmitStatus.type === 'success'
                      ? 'border-green-500/20 bg-green-500/10 text-green-200'
                      : queueSubmitStatus.type === 'info'
                        ? 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100'
                        : 'border-red-500/20 bg-red-500/10 text-red-200'
                  }`}>
                    {queueSubmitStatus.message}
                  </div>
                )}

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
            <div className="h-full min-h-0 flex flex-col md:flex-row animate-[fadeIn_0.3s_ease-out]">

              {/* Left Panel: Preview & Status */}
              <div className={`${status === 'complete' ? (isDesktopLiveAnalysisOpen ? 'w-full md:w-[30%] lg:w-[25%]' : 'w-full md:w-0 md:p-0 md:border-0 md:opacity-0') : 'w-full md:w-[55%] lg:w-[60%]'} md:h-full ${isMobileLiveAnalysisOpen ? 'h-[44dvh]' : 'h-auto'} md:max-h-none flex flex-col border-b md:border-b-0 md:border-r border-white/5 bg-black/20 p-4 md:p-6 overflow-hidden md:overflow-y-auto custom-scrollbar touch-scroll transition-all duration-500 ease-in-out`}>
                <div className="mb-4 md:mb-6 flex items-center justify-between gap-3">
                  <h2 className="text-lg font-semibold flex items-center gap-2">
                    <Activity className={`text-primary ${status === 'processing' ? 'animate-pulse' : ''}`} size={20} />
                    Live-Analyse
                  </h2>
                  <div className="flex items-center gap-2">
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
                    <button
                      type="button"
                      onClick={() => setIsMobileLiveAnalysisOpen((prev) => !prev)}
                      className="md:hidden inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-zinc-300 hover:text-white hover:bg-white/10"
                    >
                      <span>{isMobileLiveAnalysisOpen ? 'Ausblenden' : 'Einblenden'}</span>
                      <ChevronDown size={13} className={`transition-transform ${isMobileLiveAnalysisOpen ? '' : '-rotate-90'}`} />
                    </button>
                  </div>
                </div>

                {showMobileProcessingIndicator && (
                  <div className="md:hidden mb-3 rounded-xl border border-primary/20 bg-primary/5 p-3">
                    <div className="flex items-center justify-between gap-2 text-[11px]">
                      <span className="text-primary font-semibold">{mobileProcessingProgress.title}</span>
                      <span className="text-zinc-300 tabular-nums">{mobileProcessingProgress.percent}%</span>
                    </div>
                    <div className="mt-2 h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-cyan-400 via-primary to-yellow-400 transition-all duration-700 ease-out"
                        style={{ width: `${mobileProcessingProgress.percent}%` }}
                      />
                    </div>
                    <p className="mt-2 text-[10px] text-zinc-400">
                      {mobileProcessingProgress.hint} Job laeuft weiter, bitte etwas Geduld.
                    </p>
                  </div>
                )}

                <div className={`${isMobileLiveAnalysisOpen ? 'flex' : 'hidden'} ${status === 'complete' && !isDesktopLiveAnalysisOpen ? 'md:hidden' : 'md:flex'} flex-1 min-h-0 flex-col gap-4`}>
                  {status === 'error' && !jobId && processingMedia && (
                    <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4">
                      <p className="text-sm text-red-100">
                        Der Auftrag wurde noch nicht angelegt. Die Quelle ist erhalten und kann mit dem aktiven KI-Provider erneut gestartet werden.
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => handleProcess(processingMedia)}
                          disabled={isQueueSubmitting}
                          className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-black hover:bg-primary/90 disabled:opacity-50"
                        >
                          <RotateCcw size={15} />
                          Erneut starten
                        </button>
                        <button
                          type="button"
                          onClick={() => setActiveTab('settings')}
                          className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200 hover:bg-white/10"
                        >
                          <Settings size={15} />
                          Einstellungen
                        </button>
                      </div>
                    </div>
                  )}

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
                      <div className="flex-1 p-4 overflow-y-auto font-mono text-xs space-y-1.5 custom-scrollbar touch-scroll text-zinc-400">
                        {displayLogs.map((log, i) => (
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
              </div>

              {/* Right Panel: Results Grid */}
              <div className={`${status === 'complete' ? (isDesktopLiveAnalysisOpen ? 'w-full md:w-[70%] lg:w-[75%]' : 'w-full') : 'w-full md:w-[45%] lg:w-[40%]'} flex-1 min-h-0 md:h-full flex flex-col bg-background p-4 md:p-6 transition-all duration-500 ease-in-out`}>
                {status === 'processing' && (
                  <div className="mb-4 shrink-0 rounded-2xl border border-cyan-500/15 bg-cyan-500/5">
                    <button
                      type="button"
                      onClick={() => setIsQueuePanelOpen((value) => !value)}
                      className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-cyan-400/5"
                    >
                      <div className="min-w-0">
                        <h3 className="text-sm font-semibold text-cyan-100">Nächsten Job einreihen</h3>
                        <p className="mt-1 text-xs text-zinc-500">
                          Aktuell laufen {queueOverview?.running_count ?? (jobState === 'processing' ? 1 : 0)} / {queueOverview?.max_concurrent_jobs ?? 1}; wartend: {queueOverview?.queued_count ?? 0}.
                        </p>
                      </div>
                      <ChevronDown size={16} className={`text-cyan-100 transition-transform ${isQueuePanelOpen ? '' : '-rotate-90'}`} />
                    </button>
                    {isQueuePanelOpen && (
                      <div className="border-t border-cyan-500/10 p-3 md:p-4">
                        <MediaInput
                          onProcess={handleProcess}
                          isProcessing={isQueueSubmitting}
                          resetToken={mediaInputResetToken}
                          submitLabel="Job hinten einreihen"
                          submittingLabel="Job wird eingereiht..."
                          helperText="Der laufende Job bleibt aktiv. Dieser Job startet automatisch, sobald er vorne in der Queue ist und das Backend weiterlaeuft."
                          activeProfileName={uploadUserId}
                          profileContext={uploadProfileContexts[uploadUserId] || ''}
                        />
                        {queueSubmitStatus?.message && (
                          <div className={`mt-3 rounded-xl border px-3 py-2 text-sm ${
                            queueSubmitStatus.type === 'success'
                              ? 'border-green-500/20 bg-green-500/10 text-green-200'
                              : queueSubmitStatus.type === 'info'
                                ? 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100'
                                : 'border-red-500/20 bg-red-500/10 text-red-200'
                          }`}>
                            {queueSubmitStatus.message}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
                <div className="mb-4 flex flex-col gap-3 shrink-0">
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="min-w-0">
                      <h2 className="text-lg font-semibold flex items-center gap-2">
                        <Sparkles className="text-yellow-400" size={20} />
                        Generierte Shorts
                      </h2>
                      <p className="mt-1 text-xs text-zinc-500">
                        Beste Clips filtern, Hooks anpassen und mehrere Shorts in einem Rutsch rendern und planen.
                      </p>
                    </div>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                      {jobId && (
                        <button
                          type="button"
                          onClick={openActiveJobAnalysisContext}
                          className="inline-flex items-center gap-2 rounded-full border border-fuchsia-500/20 bg-fuchsia-500/10 px-3 py-1.5 text-xs text-fuchsia-100 hover:bg-fuchsia-500/15"
                        >
                          <Settings size={13} />
                          Profil & Analyseanweisungen
                        </button>
                      )}
                      {jobId && results?.clips?.length > 0 && (
                        <button
                          type="button"
                          onClick={() => {
                            setIsPodcastCommentTemplateEditing(false);
                            setIsPodcastDmPanelOpen(true);
                          }}
                          className="inline-flex items-center gap-2 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1.5 text-xs text-cyan-100 hover:bg-cyan-500/15"
                        >
                          <Share2 size={13} />
                          Kommentar-DM-Link
                          <span className={`h-1.5 w-1.5 rounded-full ${
                            activeJobSocialDefaults.podcastDmEnabled === true && activeJobSocialDefaults.podcastYoutubeUrl
                              ? 'bg-green-300'
                              : 'bg-zinc-500'
                          }`} />
                        </button>
                      )}
                      {status === 'complete' && (
                        <button
                          type="button"
                          onClick={() => setIsDesktopLiveAnalysisOpen((value) => !value)}
                          className="hidden md:inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-300 hover:bg-white/10"
                        >
                          <Activity size={13} />
                          {isDesktopLiveAnalysisOpen ? 'Analyse ausblenden' : 'Analyse einblenden'}
                        </button>
                      )}
                      {jobId && (
                        <button
                          type="button"
                          onClick={() => handleReanalyzeJobWithMinimax(
                            historyJobs.find((entry) => entry.job_id === jobId) || {
                              job_id: jobId,
                              result: results || null,
                              logs,
                              request: {},
                              source_label: results?.source_label || jobId,
                            }
                          )}
                          disabled={reanalyzingJobId === jobId || !minimaxKey}
                          className="inline-flex items-center gap-2 rounded-full border border-fuchsia-500/20 bg-fuchsia-500/10 px-3 py-1.5 text-xs text-fuchsia-100 hover:bg-fuchsia-500/15 disabled:opacity-50"
                        >
                          {reanalyzingJobId === jobId ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
                          Mit MiniMax neu analysieren
                        </button>
                      )}
                      {jobId && results?.clips?.length > 0 && (
                        <>
                          <button
                            type="button"
                            onClick={syncCurrentJobSocialPosts}
                            disabled={socialSyncBusy}
                            className="inline-flex items-center gap-2 rounded-full border border-red-500/20 bg-red-500/10 px-3 py-1.5 text-xs text-red-100 hover:bg-red-500/15 disabled:opacity-50"
                          >
                            {socialSyncBusy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />}
                            Upload-Post Sync
                          </button>
                          <button
                            type="button"
                            onClick={() => loadJobCalendar(jobId)}
                            disabled={jobCalendarLoading}
                            className="inline-flex items-center gap-2 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1.5 text-xs text-cyan-100 hover:bg-cyan-500/15 disabled:opacity-50"
                          >
                            {jobCalendarLoading ? <Loader2 size={13} className="animate-spin" /> : <CalendarDays size={13} />}
                            Kalender
                          </button>
                          <button
                            type="button"
                            onClick={rescheduleAllCurrentJobSocialPosts}
                            disabled={jobRescheduleAllBusy}
                            className="inline-flex items-center gap-2 rounded-full border border-fuchsia-500/20 bg-fuchsia-500/10 px-3 py-1.5 text-xs text-fuchsia-100 hover:bg-fuchsia-500/15 disabled:opacity-50"
                          >
                            {jobRescheduleAllBusy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />}
                            Reschedule all
                          </button>
                        </>
                      )}
                      {results?.clips?.length > 0 && (
                        <span className="text-xs bg-white/10 text-white px-2 py-0.5 rounded-full">
                          {filteredClipEntries.length}/{results.clips.length} Clips
                        </span>
                      )}
                      {selectedClipKeys.length > 0 && (
                        <span className="text-xs bg-fuchsia-500/10 border border-fuchsia-500/20 text-fuchsia-200 px-2 py-0.5 rounded-full">
                          {selectedClipKeys.length} ausgewaehlt
                        </span>
                      )}
                      {results?.cost_analysis && (
                        <span className="text-xs bg-green-500/10 border border-green-500/20 text-green-400 px-2 py-0.5 rounded-full" title={`Input: ${results.cost_analysis.input_tokens} | Output: ${results.cost_analysis.output_tokens}`}>
                          ${results.cost_analysis.total_cost.toFixed(5)}
                        </span>
                      )}
                    </div>
                  </div>

                  {results?.clips?.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-2 text-[11px] uppercase tracking-wide text-zinc-500">
                        <ListFilter size={13} />
                        Dauer
                      </span>
                      {[
                        { value: 'all', label: 'Alle' },
                        { value: 'under_1m', label: 'Unter 1 Min' },
                        { value: 'over_1m', label: 'Ueber 1 Min' },
                      ].map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => setClipDurationFilter(option.value)}
                          className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                            clipDurationFilter === option.value
                              ? 'border-primary/40 bg-primary/15 text-white'
                              : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white'
                          }`}
                        >
                          {option.label}
                        </button>
                      ))}
                      {[
                        { value: 'all', label: 'Alle Render-States' },
                        { value: 'rendered', label: 'Gerendert' },
                        { value: 'unrendered', label: 'Nicht gerendert' },
                      ].map((option) => (
                        <button
                          key={`render-${option.value}`}
                          type="button"
                          onClick={() => setClipRenderFilter(option.value)}
                          className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                            clipRenderFilter === option.value
                              ? 'border-cyan-500/40 bg-cyan-500/15 text-white'
                              : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white'
                          }`}
                        >
                          {option.label}
                        </button>
                      ))}
                      <button
                        type="button"
                        onClick={() => setShowSelectedOnly((prev) => !prev)}
                        disabled={!selectedClipKeys.length}
                        className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                          showSelectedOnly
                            ? 'border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-100'
                            : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white'
                        } disabled:cursor-not-allowed disabled:opacity-40`}
                      >
                        {showSelectedOnly ? 'Alle anzeigen' : 'Nur Auswahl'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setShowUnpostedOnly((prev) => !prev)}
                        className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                          showUnpostedOnly
                            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
                            : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white'
                        }`}
                      >
                        {showUnpostedOnly ? 'Alle Posting-States' : 'Nicht gepostet'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setShowFailedPostsOnly((prev) => !prev)}
                        className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                          showFailedPostsOnly
                            ? 'border-red-500/30 bg-red-500/10 text-red-100'
                            : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white'
                        }`}
                      >
                        {showFailedPostsOnly ? 'Alle Posting-Fehler' : 'Fehlgeschlagen'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setHideFillerStarts((prev) => !prev)}
                        className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                          hideFillerStarts
                            ? 'border-amber-500/30 bg-amber-500/10 text-amber-100'
                            : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white'
                        }`}
                      >
                        {hideFillerStarts ? 'Filler-Starts anzeigen' : 'Filler-Starts ausblenden'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeferPreviewLoading((prev) => !prev)}
                        className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                          deferPreviewLoading
                            ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100'
                            : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white'
                        }`}
                      >
                        {deferPreviewLoading ? 'Previews manuell laden' : 'Vorhandene Previews direkt laden'}
                      </button>
                      <button
                        type="button"
                        onClick={selectAllVisibleClips}
                        disabled={!filteredClipEntries.length}
                        className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-300 hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        Alle sichtbaren auswaehlen
                      </button>
                      {selectedClipKeys.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setSelectedClipKeys([])}
                          className="ml-auto rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-300 hover:bg-white/10 hover:text-white"
                        >
                          Auswahl loeschen
                        </button>
                      )}
                    </div>
                  )}

                  {(socialSyncStatus?.message || (bulkStatus?.message && !showBulkActionsBar)) && (
                    <div className={`rounded-xl border px-3 py-2 text-sm ${
                      (socialSyncStatus?.type || bulkStatus?.type) === 'success'
                        ? 'border-green-500/20 bg-green-500/10 text-green-200'
                        : (socialSyncStatus?.type || bulkStatus?.type) === 'warning'
                          ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                          : (socialSyncStatus?.type || bulkStatus?.type) === 'info'
                            ? 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100'
                            : 'border-red-500/20 bg-red-500/10 text-red-200'
                    }`}>
                      {socialSyncStatus?.message || bulkStatus?.message}
                    </div>
                  )}

                  {jobId && isAnalysisContextOpen && (
                    <div className="fixed inset-0 z-[180] flex items-center justify-center p-4">
                      <button
                        type="button"
                        aria-label="Dialog schliessen"
                        onClick={() => setIsAnalysisContextOpen(false)}
                        className="absolute inset-0 bg-black/75 backdrop-blur-sm"
                      />
                      <div className="relative z-10 max-h-[88vh] w-full max-w-4xl overflow-y-auto rounded-3xl border border-fuchsia-400/20 bg-zinc-950 shadow-2xl shadow-fuchsia-950/40">
                        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-white/10 bg-zinc-950/95 px-5 py-4 backdrop-blur">
                          <div>
                            <h3 className="text-lg font-semibold text-white">Profil & Analyseanweisungen</h3>
                            <p className="mt-1 text-xs text-zinc-400">Kanalbeschreibung profilweit verwalten oder den aktuellen Entwurf nur diesem Job zuweisen.</p>
                          </div>
                          <button
                            type="button"
                            onClick={() => setIsAnalysisContextOpen(false)}
                            className="rounded-full border border-white/10 bg-white/5 p-2 text-zinc-300 hover:bg-white/10 hover:text-white"
                            aria-label="Schliessen"
                          >
                            <X size={16} />
                          </button>
                        </div>
                        <div className="grid gap-5 p-5 lg:grid-cols-2">
                          <div>
                            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Upload-Post-Profil</label>
                            <select
                              value={activeJobAnalysisContext.profileName || uploadUserId || ''}
                              onChange={(event) => {
                                const profileName = event.target.value;
                                setActiveJobAnalysisContext((previous) => ({
                                  ...previous,
                                  profileName,
                                  profileContext: uploadProfileContexts[profileName] || '',
                                }));
                              }}
                              className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white"
                            >
                              <option value="">Nicht zugeordnet</option>
                              {userProfiles.map((profile) => <option key={profile.username} value={profile.username}>{profile.username}</option>)}
                            </select>
                            <label className="mb-1 mt-4 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Kanalbeschreibung</label>
                            <textarea
                              value={activeJobAnalysisContext.profileContext}
                              onChange={(event) => setActiveJobAnalysisContext((previous) => ({ ...previous, profileContext: event.target.value }))}
                              rows={7}
                              className="w-full resize-y rounded-xl border border-white/10 bg-black/40 p-3 text-sm text-white"
                              placeholder="Kanalbeschreibung, Zielgruppe, Tonalitaet und Themenschwerpunkte"
                            />
                            <p className="mt-2 text-xs text-zinc-500">Profilübergreifend speichern übernimmt diese Beschreibung automatisch für künftig angelegte Jobs dieses Profils.</p>
                          </div>
                          <div>
                            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Anweisungen fuer diesen Job</label>
                            <textarea
                              value={activeJobAnalysisContext.jobInstructions}
                              onChange={(event) => setActiveJobAnalysisContext((previous) => ({ ...previous, jobInstructions: event.target.value }))}
                              rows={11}
                              className="w-full resize-y rounded-xl border border-white/10 bg-black/40 p-3 text-sm text-white"
                              placeholder="Z. B. Titel immer mit einem bestimmten Wort beginnen lassen oder einen inhaltlichen Schwerpunkt setzen."
                            />
                            <p className="mt-2 text-xs text-zinc-500">Job-Anweisungen bleiben ausschließlich bei diesem Job und werden bei einer erneuten Analyse berücksichtigt.</p>
                          </div>
                        </div>
                        <div className="flex flex-wrap justify-end gap-3 border-t border-white/10 bg-black/20 px-5 py-4">
                          <button
                            type="button"
                            onClick={saveActiveProfileContext}
                            disabled={!String(activeJobAnalysisContext.profileName || uploadUserId || '').trim()}
                            className="rounded-xl border border-cyan-400/20 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/15 disabled:opacity-40"
                          >
                            Profilübergreifend speichern
                          </button>
                          <button
                            type="button"
                            onClick={saveActiveJobAnalysisContext}
                            disabled={analysisContextSaving}
                            className="rounded-xl border border-fuchsia-400/20 bg-fuchsia-500/10 px-4 py-2 text-sm font-semibold text-fuchsia-100 hover:bg-fuchsia-500/15 disabled:opacity-50"
                          >
                            {analysisContextSaving ? 'Speichert...' : 'Nur fuer diesen Job speichern'}
                          </button>
                        </div>
                      </div>
                    </div>
                  )}

                  {jobId && results?.clips?.length > 0 && isPodcastDmPanelOpen && (
                    <div className="fixed inset-0 z-[180] flex items-center justify-center p-4">
                      <button
                        type="button"
                        aria-label="Dialog schliessen"
                        onClick={() => setIsPodcastDmPanelOpen(false)}
                        className="absolute inset-0 bg-black/75 backdrop-blur-sm"
                      />
                      <div className="relative z-10 w-full max-w-3xl rounded-3xl border border-cyan-400/20 bg-zinc-950 shadow-2xl shadow-cyan-950/30">
                        <div className="flex items-start justify-between gap-4 border-b border-white/10 px-5 py-4">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="text-lg font-semibold text-white">Kommentar-DM-Link</h3>
                              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                                activeJobSocialDefaults.podcastDmEnabled === true && activeJobSocialDefaults.podcastYoutubeUrl
                                  ? 'bg-green-400/15 text-green-200'
                                  : 'bg-zinc-500/15 text-zinc-300'
                              }`}>
                                {activeJobSocialDefaults.podcastDmEnabled === true && activeJobSocialDefaults.podcastYoutubeUrl
                                  ? 'Aktiv fuer Instagram'
                                  : 'Inaktiv'}
                              </span>
                            </div>
                            <p className="mt-1 text-xs text-zinc-400">Ziel-Link und Kommentar-Keyword für diesen Job festlegen.</p>
                          </div>
                          <button
                            type="button"
                            onClick={() => setIsPodcastDmPanelOpen(false)}
                            className="rounded-full border border-white/10 bg-white/5 p-2 text-zinc-300 hover:bg-white/10 hover:text-white"
                            aria-label="Schliessen"
                          >
                            <X size={16} />
                          </button>
                        </div>
                        <div className="p-5">
                          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_180px]">
                            <div>
                              <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-cyan-100/80">Ziel-Link</label>
                              <input
                                type="url"
                                value={activeJobSocialDefaults.podcastYoutubeUrl}
                                onChange={(event) => updatePodcastLinkDraftForJob(jobId, { podcastYoutubeUrl: event.target.value })}
                                className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:border-cyan-400/50 focus:outline-none"
                                placeholder="https://example.com/podcast-oder-tutorial"
                              />
                            </div>
                            <div>
                              <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-cyan-100/80">Keyword</label>
                              <input
                                type="text"
                                value={activeJobSocialDefaults.podcastKeyword}
                                onChange={(event) => updatePodcastLinkDraftForJob(jobId, { podcastKeyword: event.target.value })}
                                className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:border-cyan-400/50 focus:outline-none"
                                placeholder="Video"
                              />
                            </div>
                          </div>
                          <div className="mt-4 rounded-xl border border-white/10 bg-black/30 p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <label className="block text-xs font-semibold uppercase tracking-wide text-cyan-100/80">CTA in Caption und First Comment</label>
                                <p className="mt-1 text-xs text-zinc-500">Der Platzhalter <code className="text-cyan-200">&lt;keyword&gt;</code> wird beim Posting durch das Keyword ersetzt.</p>
                              </div>
                              <button
                                type="button"
                                onClick={() => setIsPodcastCommentTemplateEditing((value) => !value)}
                                className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-zinc-200 hover:bg-white/10"
                              >
                                {isPodcastCommentTemplateEditing ? 'Vorschau' : 'Bearbeiten'}
                              </button>
                            </div>
                            {isPodcastCommentTemplateEditing ? (
                              <>
                                <textarea
                                  value={activeJobSocialDefaults.podcastCommentTemplate}
                                  onChange={(event) => updatePodcastLinkDraftForJob(jobId, { podcastCommentTemplate: event.target.value })}
                                  rows={3}
                                  className="mt-3 w-full resize-y rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:border-cyan-400/50 focus:outline-none"
                                  placeholder={DEFAULT_PODCAST_COMMENT_TEMPLATE}
                                />
                                {!String(activeJobSocialDefaults.podcastCommentTemplate || '').toLowerCase().includes('<keyword>') && (
                                  <p className="mt-2 text-xs text-amber-300">Bitte den Platzhalter &lt;keyword&gt; verwenden.</p>
                                )}
                              </>
                            ) : (
                              <div className="mt-3 rounded-lg border border-cyan-400/15 bg-cyan-400/5 px-3 py-2 text-sm text-cyan-50">
                                {renderPodcastCommentTemplate(
                                  activeJobSocialDefaults.podcastCommentTemplate,
                                  activeJobSocialDefaults.podcastKeyword,
                                )}
                              </div>
                            )}
                          </div>
                          <label className="mt-4 flex items-center gap-3 rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm text-zinc-200">
                            <input
                              type="checkbox"
                              checked={activeJobSocialDefaults.podcastDmEnabled === true}
                              onChange={(event) => updatePodcastLinkDraftForJob(jobId, { podcastDmEnabled: event.target.checked })}
                              className="h-4 w-4 rounded border-zinc-600 bg-black/50 text-cyan-400 focus:ring-cyan-400"
                            />
                            Kommentar-DM-Automation fuer Instagram aktivieren
                          </label>
                          <p className="mt-3 text-xs text-cyan-100/65">
                            Die CTA wird aktuell nur bei Instagram in Caption und First Comment ergänzt. Andere Plattformen posten unverändert; das Relay registriert nur von Upload-Post unterstützte Kommentar-DMs.
                          </p>
                        </div>
                        <div className="flex justify-end gap-3 border-t border-white/10 bg-black/20 px-5 py-4">
                          <button
                            type="button"
                            onClick={() => setIsPodcastDmPanelOpen(false)}
                            className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-zinc-300 hover:bg-white/10"
                          >
                            Abbrechen
                          </button>
                          <button
                            type="button"
                            onClick={async () => {
                              const result = await applyPodcastLinkToJob(jobId, activeJobSocialDefaults);
                              if (result?.success) setIsPodcastCommentTemplateEditing(false);
                            }}
                            disabled={!String(activeJobSocialDefaults.podcastCommentTemplate || '').toLowerCase().includes('<keyword>')}
                            className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-400/20 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/15"
                          >
                            Fuer diesen Job speichern
                          </button>
                          <button
                            type="button"
                            onClick={async () => {
                              const saved = await applyPodcastLinkToJob(jobId, activeJobSocialDefaults);
                              if (!saved?.success) return;
                              setIsPodcastCommentTemplateEditing(false);
                              await repairPodcastCampaignSchedules({
                                jobIds: [jobId],
                                profileUsername: activeJobUploadProfile,
                              }).catch(() => {});
                            }}
                            disabled={
                              podcastCampaignRepairBusy
                              || activeJobSocialDefaults.podcastDmEnabled !== true
                              || !String(activeJobSocialDefaults.podcastYoutubeUrl || '').trim()
                              || !String(activeJobSocialDefaults.podcastCommentTemplate || '').toLowerCase().includes('<keyword>')
                            }
                            className="inline-flex items-center justify-center gap-2 rounded-xl border border-amber-400/25 bg-amber-400/10 px-4 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-400/15 disabled:opacity-40"
                          >
                            {podcastCampaignRepairBusy ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
                            Speichern + bestehende Posts reparieren
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className={`flex-1 min-h-0 overflow-y-auto custom-scrollbar touch-scroll p-1 ${
                  showBulkActionsBar
                    ? (isBulkBarCollapsed ? 'pb-32 md:pb-28' : 'pb-[30rem] md:pb-[24rem]')
                    : ''
                }`}>
                  {results && results.clips && results.clips.length > 0 ? (
                    filteredClipEntries.length > 0 ? (
                    <div className="grid grid-cols-1 gap-4 pb-10">
                      {filteredClipEntries.map(({ clip, index: i, key, hookDraftText }) => (
                        <ResultCard
                          key={key}
                          clip={clip}
                          index={i}
                          jobId={jobId}
                          uploadPostKey={uploadPostKey}
                          uploadUserId={activeJobUploadProfile}
                          geminiApiKey={apiKey}
                          geminiModel={geminiModel}
                          openaiKey={openaiKey}
                          openaiModel={openaiModel}
                          claudeKey={claudeKey}
                          claudeModel={claudeModel}
                          minimaxKey={minimaxKey}
                          minimaxAuthMode={minimaxAuthMode}
                          minimaxModel={minimaxModel}
                          llmProvider={llmProvider}
                          ollamaBaseUrl={ollamaBaseUrl}
                          ollamaModel={ollamaModel}
                          elevenLabsKey={elevenLabsKey}
                          subtitleStyle={activeJobOverlayDefaults.subtitleStyle}
                          hookStyle={activeJobOverlayDefaults.hookStyle}
                          tightEditPreset={tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset}
                          socialPostSettings={socialPostSettings}
                          jobInstagramCollaborators={activeJobSocialDefaults.instagramCollaborators}
                          podcastDmSettings={podcastDmSettings}
                          activeUploadProfile={activeJobUploadProfile}
                          onApplySubtitleDefaultsToJob={(style) => applySubtitleDefaultsToJob(jobId, style)}
                          onApplyHookDefaultsToJob={(style) => applyHookDefaultsToJob(jobId, style)}
                          onApplyInstagramCollaboratorsToJob={(value) => applyInstagramCollaboratorsToJob(jobId, value)}
                          currentVideoOverride={clipVideoOverrides[getClipVariantKey(jobId, clip, i)]}
                          pexelsKey={pexelsKey}
                          onVideoVariantChange={(videoUrl) => updateClipVideoOverride(jobId, clip, i, videoUrl)}
                          onClipUpdated={(updatedClip) => updateClipResult(jobId, updatedClip)}
                          onPlay={(time) => handleClipPlay(time)}
                          onPause={handleClipPause}
                          hookDraftText={hookDraftText}
                          onHookDraftChange={(value) => updateClipHookDraft(clip, i, value)}
                          deferPreviewLoading={deferPreviewLoading}
                          isSelected={selectedClipKeys.includes(key)}
                          onToggleSelect={() => toggleClipSelection(clip, i)}
                        />
                      ))}
                    </div>
                    ) : (
                      <div className="h-full flex flex-col items-center justify-center text-zinc-500 space-y-3 opacity-80">
                        <div className="w-12 h-12 rounded-full border border-white/10 bg-white/5 flex items-center justify-center">
                          <ListFilter size={18} />
                        </div>
                        <p className="text-sm">
                          {showSelectedOnly
                            ? 'In der aktuellen Auswahl ist kein Clip sichtbar.'
                            : clipRenderFilter === 'rendered'
                              ? 'Kein Clip ist aktuell gerendert.'
                              : clipRenderFilter === 'unrendered'
                                ? 'Kein Clip ist aktuell im Rohzustand.'
                            : showUnpostedOnly
                              ? 'Kein Clip passt zum Filter Nicht gepostet.'
                              : showFailedPostsOnly
                                ? 'Kein Clip passt zum Filter Fehlgeschlagen.'
                                : hideFillerStarts
                                  ? 'Alle sichtbaren Clips starten aktuell mit einem markierten Fuellwort.'
                                  : 'Kein Clip passt zum aktiven Filter.'}
                        </p>
                      </div>
                    )
                  ) : (
                    status === 'processing' ? (
                      <div className="h-full flex flex-col items-center justify-center text-zinc-500 space-y-4 opacity-50">
                        <div className="w-12 h-12 rounded-full border-2 border-zinc-800 border-t-primary animate-spin" />
                        <p className="text-sm">Warte auf Clips...</p>
                      </div>
                    ) : status === 'error' ? (
                      <div className="h-full flex flex-col items-center justify-center text-red-400 space-y-2">
                        <p>Generierung fehlgeschlagen.</p>
                      </div>
                    ) : null
                  )}
                </div>
              </div>

              {showBulkActionsBar && (
                <div className="fixed inset-x-3 bottom-3 z-[3500] md:inset-x-6">
                  <div className="mx-auto w-full max-w-6xl rounded-2xl border border-white/10 bg-[#121214]/95 backdrop-blur-xl shadow-2xl shadow-black/40">
                    <div className="flex flex-col gap-4 p-4 md:p-5">
                      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded-full border border-fuchsia-500/30 bg-fuchsia-500/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-fuchsia-200">
                              {currentBulkOperation?.total_count || selectedClipKeys.length} Shorts
                            </span>
                            {(bulkProgress || currentBulkOperation) && (
                              <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-cyan-200">
                                {currentBulkOperation
                                  ? formatBulkOperationSummary(currentBulkOperation)
                                  : `${bulkProgress.current}/${bulkProgress.total} ${bulkProgress.phase === 'render' ? 'Render' : 'Planung'}`}
                              </span>
                            )}
                            {currentBulkOperation && (bulkOperationIsRunning || bulkOperationCanResume) && (
                              <span className={`rounded-full border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide ${
                                bulkOperationIsRunning
                                  ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100'
                                  : bulkOperationCanResume
                                    ? 'border-amber-500/30 bg-amber-500/10 text-amber-100'
                                    : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
                              }`}>
                                {currentBulkOperation.status}
                              </span>
                            )}
                          </div>
                          <p className="mt-2 text-xs text-zinc-400">
                            {(currentBulkOperation && (bulkOperationIsRunning || bulkOperationCanResume) && currentBulkOperation.message)
                              ? currentBulkOperation.message
                              : isBulkBarCollapsed
                              ? 'Multi-Post-Leiste minimiert. Erweitern, um Reihenfolge, Timing und Posting-Optionen zu bearbeiten.'
                              : 'Quick-Render nutzt globale Untertitel- und Hook-Vorgaben. Die Reihenfolge-Liste bestimmt die Posting-Reihenfolge.'}
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setIsBulkOrderOpen((prev) => !prev)}
                            disabled={!selectedClipEntries.length}
                            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200 hover:bg-white/10"
                          >
                            <GripVertical size={15} />
                            {isBulkOrderOpen ? 'Reihenfolge zu' : 'Reihenfolge'}
                          </button>
                          <button
                            type="button"
                            onClick={() => setIsBulkSettingsOpen((prev) => !prev)}
                            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200 hover:bg-white/10"
                          >
                            <Settings size={15} />
                            Einstellungen
                          </button>
                          <button
                            type="button"
                            onClick={() => setSelectedClipKeys([])}
                            disabled={isBulkScheduling || bulkOperationIsRunning}
                            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-300 hover:bg-white/10 disabled:opacity-50"
                          >
                            <X size={15} />
                            Auswahl leeren
                          </button>
                          {currentBulkOperation && (bulkOperationIsRunning || bulkOperationCanResume) ? (
                            <>
                              {bulkOperationIsRunning ? (
                                <button
                                  type="button"
                                  onClick={handlePauseBulkOperation}
                                  disabled={bulkControlBusy === 'pause'}
                                  className="inline-flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm font-medium text-amber-100 hover:bg-amber-500/15 disabled:opacity-60"
                                >
                                  {bulkControlBusy === 'pause' ? <Loader2 size={16} className="animate-spin" /> : <Clock3 size={16} />}
                                  Pause
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  onClick={handleResumeBulkOperation}
                                  disabled={bulkControlBusy === 'resume'}
                                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-600 to-sky-600 px-4 py-2.5 text-sm font-semibold text-white hover:from-cyan-500 hover:to-sky-500 disabled:opacity-60"
                                >
                                  {bulkControlBusy === 'resume' ? <Loader2 size={16} className="animate-spin" /> : <Share2 size={16} />}
                                  Fortsetzen
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={handleStopBulkOperation}
                                disabled={bulkControlBusy === 'stop'}
                                className="inline-flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-sm font-medium text-red-200 hover:bg-red-500/15 disabled:opacity-60"
                              >
                                {bulkControlBusy === 'stop' ? <Loader2 size={16} className="animate-spin" /> : <X size={16} />}
                                Stop
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                onClick={() => handleBulkAction(BULK_OPERATION_MODES.RENDER_ONLY)}
                                disabled={isBulkScheduling}
                                className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors disabled:opacity-60 ${
                                  bulkOperationMode === BULK_OPERATION_MODES.RENDER_ONLY
                                    ? 'border-fuchsia-500/50 bg-fuchsia-500/15 text-fuchsia-100 hover:bg-fuchsia-500/20'
                                    : 'border-white/10 bg-white/5 text-zinc-200 hover:bg-white/10'
                                }`}
                              >
                                {isBulkScheduling && bulkOperationMode === BULK_OPERATION_MODES.RENDER_ONLY
                                  ? <Loader2 size={16} className="animate-spin" />
                                  : <Sparkles size={16} />}
                                {isBulkScheduling && bulkOperationMode === BULK_OPERATION_MODES.RENDER_ONLY
                                  ? BULK_OPERATION_CONFIG[BULK_OPERATION_MODES.RENDER_ONLY].progressButtonLabel
                                  : BULK_OPERATION_CONFIG[BULK_OPERATION_MODES.RENDER_ONLY].label}
                              </button>
                              <button
                                type="button"
                                onClick={() => handleBulkAction(BULK_OPERATION_MODES.POST_ONLY)}
                                disabled={isBulkScheduling}
                                className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors disabled:opacity-60 ${
                                  bulkOperationMode === BULK_OPERATION_MODES.POST_ONLY
                                    ? 'border-cyan-500/50 bg-cyan-500/15 text-cyan-100 hover:bg-cyan-500/20'
                                    : 'border-white/10 bg-white/5 text-zinc-200 hover:bg-white/10'
                                }`}
                              >
                                {isBulkScheduling && bulkOperationMode === BULK_OPERATION_MODES.POST_ONLY
                                  ? <Loader2 size={16} className="animate-spin" />
                                  : <CalendarDays size={16} />}
                                {isBulkScheduling && bulkOperationMode === BULK_OPERATION_MODES.POST_ONLY
                                  ? BULK_OPERATION_CONFIG[BULK_OPERATION_MODES.POST_ONLY].progressButtonLabel
                                  : BULK_OPERATION_CONFIG[BULK_OPERATION_MODES.POST_ONLY].label}
                              </button>
                              <button
                                type="button"
                                onClick={() => handleBulkAction(BULK_OPERATION_MODES.RENDER_AND_POST)}
                                disabled={isBulkScheduling}
                                className={`inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-all disabled:opacity-60 ${
                                  bulkOperationMode === BULK_OPERATION_MODES.RENDER_AND_POST
                                    ? 'bg-gradient-to-r from-fuchsia-600 to-pink-600 hover:from-fuchsia-500 hover:to-pink-500'
                                    : 'bg-gradient-to-r from-zinc-700 to-zinc-600 hover:from-zinc-600 hover:to-zinc-500'
                                }`}
                              >
                                {isBulkScheduling && bulkOperationMode === BULK_OPERATION_MODES.RENDER_AND_POST
                                  ? <Loader2 size={16} className="animate-spin" />
                                  : <Share2 size={16} />}
                                {isBulkScheduling && bulkOperationMode === BULK_OPERATION_MODES.RENDER_AND_POST
                                  ? BULK_OPERATION_CONFIG[BULK_OPERATION_MODES.RENDER_AND_POST].progressButtonLabel
                                  : BULK_OPERATION_CONFIG[BULK_OPERATION_MODES.RENDER_AND_POST].label}
                              </button>
                            </>
                          )}
                          <button
                            type="button"
                            onClick={() => setIsBulkBarCollapsed((prev) => !prev)}
                            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200 hover:bg-white/10"
                          >
                            <ChevronDown size={15} className={`transition-transform ${isBulkBarCollapsed ? 'rotate-180' : ''}`} />
                            {isBulkBarCollapsed ? 'Erweitern' : 'Minimieren'}
                          </button>
                        </div>
                      </div>

                      {!isBulkBarCollapsed && isBulkOrderOpen && (
                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                          <div className="mb-2 flex items-center justify-between gap-2">
                            <label className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
                              Posting-Reihenfolge
                            </label>
                            <span className="text-[11px] text-zinc-500">Vertikal ziehen und ablegen</span>
                          </div>
                          <div className="max-h-56 space-y-2 overflow-y-auto custom-scrollbar pr-1">
                            {selectedClipEntries.map((entry, orderIndex) => (
                              <div
                                key={entry.key}
                                draggable
                                onDragStart={(event) => handleSelectedClipDragStart(event, entry.key)}
                                onDragOver={(event) => handleSelectedClipDragOver(event, entry.key)}
                                onDrop={(event) => handleSelectedClipDrop(event, entry.key)}
                                onDragEnd={handleSelectedClipDragEnd}
                                className={`cursor-grab rounded-xl border px-3 py-2 transition-colors active:cursor-grabbing ${
                                  draggedSelectedClipKey === entry.key
                                    ? 'border-fuchsia-500/40 bg-fuchsia-500/15 text-fuchsia-100'
                                    : dragOverSelectedClipKey === entry.key
                                      ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-100'
                                      : 'border-white/10 bg-white/5 text-zinc-200 hover:bg-white/10'
                                }`}
                              >
                                <div className="flex items-center gap-3">
                                  <GripVertical size={15} className="shrink-0 text-zinc-500" />
                                  <span className="rounded-full bg-black/40 px-1.5 py-0.5 font-mono text-[10px] text-zinc-300">
                                    {orderIndex + 1}
                                  </span>
                                  <div className="min-w-0 flex-1">
                                    <div className="truncate text-sm font-medium text-white">
                                      {entry.clip.video_title_for_youtube_short || `Clip ${entry.index + 1}`}
                                    </div>
                                    <div className="text-[11px] text-zinc-500">
                                      Clip {entry.index + 1}
                                    </div>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {!isBulkBarCollapsed && (
                        <div className="grid gap-3 md:grid-cols-[180px_140px_140px_minmax(0,1fr)] xl:grid-cols-[180px_140px_140px_minmax(0,1fr)_minmax(0,1fr)]">
                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                          <label className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
                            <CalendarDays size={14} />
                            Startdatum
                          </label>
                          <input
                            type="date"
                            value={bulkScheduleDate}
                            min={formatDateInputValue()}
                            onChange={(e) => setBulkScheduleDate(e.target.value)}
                            className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                          />
                        </div>

                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                          <label className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
                            <CalendarDays size={14} />
                            Alle X Tage
                          </label>
                          <input
                            type="number"
                            min="1"
                            step="1"
                            value={bulkScheduleDayInterval}
                            onChange={(e) => setBulkScheduleDayInterval(Math.max(1, Number(e.target.value) || 1))}
                            className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                          />
                          <p className="mt-2 text-[11px] text-zinc-500">
                            `1` = taeglich, `3` = jeder dritte Tag.
                          </p>
                        </div>

                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                          <label className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
                            <SkipForward size={14} />
                            Skip
                          </label>
                          <input
                            type="number"
                            min="0"
                            step="1"
                            value={bulkSkipCount}
                            onChange={(e) => setBulkSkipCount(Math.max(0, Number(e.target.value) || 0))}
                            className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                          />
                          <p className="mt-2 text-[11px] text-zinc-500">
                            Ueberspringt die ersten {normalizedBulkSkipCount} ausgewaehlten Shorts und setzt beim naechsten Slot fort.
                          </p>
                        </div>

                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                          <label className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
                            <Clock3 size={14} />
                            Posting-Slots pro Tag
                          </label>
                          <input
                            type="text"
                            value={bulkScheduleSlots}
                            onChange={(e) => setBulkScheduleSlots(e.target.value)}
                            className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                            placeholder="12:00, 15:00, 18:00"
                          />
                          <p className="mt-2 text-[11px] text-zinc-500">
                            Kommagetrennt, Format `HH:MM`. Nach jedem Tagesblock springt der Plan um das eingestellte Tagesintervall weiter.
                          </p>
                          <label className="mt-3 flex items-start gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200">
                            <input
                              type="checkbox"
                              checked={bulkScheduleStaggerSlotsByDay}
                              onChange={(e) => setBulkScheduleStaggerSlotsByDay(e.target.checked)}
                              className="mt-0.5 h-4 w-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                            />
                            <span className="min-w-0">
                              <span className="block text-sm font-medium text-white">Slots ueber Tage staffeln</span>
                              <span className="mt-1 block text-[11px] text-zinc-500">
                                Aktiv: der erste geplante Post startet immer mit dem ersten Slot aus deiner Eingabe, danach folgt pro Intervalltag der naechste Slot, z. B. `18:00`, dann `15:00`, dann `12:00`.
                              </span>
                            </span>
                          </label>
                        </div>

                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
                            Nächste Slots
                          </div>
                          <div className="mb-2 text-[11px] text-zinc-500">
                            {bulkProcessEntries.length > 0
                              ? `${bulkProcessEntries.length} Shorts werden verarbeitet.`
                              : 'Mit dem aktuellen Skip bleibt keine Short mehr uebrig.'}
                          </div>
                          {bulkSchedulePreviewError ? (
                            <p className="text-[11px] text-red-300">{bulkSchedulePreviewError}</p>
                          ) : bulkSchedulePreview.length ? (
                            <div className="flex flex-wrap gap-2">
                              {bulkSchedulePreview.map((slot) => (
                                <span key={slot.toISOString()} className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-zinc-200">
                                  {formatSchedulePreviewLabel(slot)}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <p className="text-[11px] text-zinc-500">Waehle mindestens zwei Shorts aus.</p>
                          )}
                        </div>
                        </div>
                      )}

                      {!isBulkBarCollapsed && isBulkSettingsOpen && (
                        <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <h3 className="text-sm font-semibold text-white">Posting-Einstellungen</h3>
                              <p className="mt-1 text-xs text-zinc-500">
                                Diese Optionen werden fuer alle ausgewaehlten Shorts und alle kuenftigen Bulk-Posts verwendet.
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => setIsBulkSettingsOpen(false)}
                              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-300 hover:bg-white/10"
                            >
                              Schliessen
                            </button>
                          </div>

                          <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_1fr]">
                            <div className="space-y-4">
                              <div>
                                <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Plattformen</label>
                                <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                                  {SOCIAL_PLATFORM_OPTIONS.map((platform) => (
                                    <label key={platform.key} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200">
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
                                        className="h-4 w-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                      />
                                      {platform.label}
                                    </label>
                                  ))}
                                </div>
                              </div>

                              <div>
                                <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Erster Kommentar</label>
                                <textarea
                                  value={bulkFirstComment}
                                  onChange={(e) => setBulkFirstComment(e.target.value)}
                                  rows={3}
                                  className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                  placeholder="Optionaler erster Kommentar fuer alle Posts"
                                />
                              </div>
                            </div>

                            <div className="space-y-4">
                              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
                                <div>
                                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Instagram-Modus</label>
                                  <select
                                    value={socialPostSettings.instagramShareMode}
                                    onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, instagramShareMode: e.target.value }))}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                  >
                                    {INSTAGRAM_SHARE_MODES.map((mode) => (
                                      <option key={mode.value} value={mode.value}>{mode.label}</option>
                                    ))}
                                  </select>
                                </div>
                                <div>
                                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">
                                    Instagram-Collaborator
                                  </label>
                                  <input
                                    type="text"
                                    value={activeJobSocialDefaults.instagramCollaborators}
                                    onChange={(e) => updateInstagramCollaboratorsDraftForJob(jobId, e.target.value)}
                                    onBlur={(e) => applyInstagramCollaboratorsToJob(jobId, e.target.value)}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                    placeholder="Optional, ohne @, z. B. partner_account"
                                  />
                                  <p className="mt-2 text-[11px] text-zinc-500">
                                    Gilt fuer den ganzen Job. Mit oder ohne `@` moeglich, empfohlen ohne `@`. Auf Clip-Ebene kann der Wert optional ueberschrieben oder leer gelassen werden.
                                  </p>
                                </div>
                                <div>
                                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">TikTok-Modus</label>
                                  <select
                                    value={socialPostSettings.tiktokPostMode}
                                    onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, tiktokPostMode: e.target.value }))}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                  >
                                    {TIKTOK_POST_MODES.map((mode) => (
                                      <option key={mode.value} value={mode.value}>{mode.label}</option>
                                    ))}
                                  </select>
                                </div>
                              </div>

                              <label className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-3 py-3 text-sm text-zinc-200">
                                <input
                                  type="checkbox"
                                  checked={!!socialPostSettings.tiktokIsAigc}
                                  onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, tiktokIsAigc: e.target.checked }))}
                                  className="h-4 w-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                />
                                TikTok als KI-generiert markieren
                              </label>

                              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
                                <div>
                                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Facebook-Page-ID</label>
                                  <input
                                    type="text"
                                    value={socialPostSettings.facebookPageId}
                                    onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, facebookPageId: e.target.value }))}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                    placeholder="Optional"
                                  />
                                </div>
                                <div>
                                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Pinterest-Board-ID</label>
                                  <input
                                    type="text"
                                    value={socialPostSettings.pinterestBoardId}
                                    onChange={(e) => setSocialPostSettings((prev) => ({ ...prev, pinterestBoardId: e.target.value }))}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                    placeholder="Fuer Pinterest erforderlich"
                                  />
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {bulkStatus?.message && (
                        <div className={`rounded-xl border px-3 py-2 text-sm ${
                          bulkStatus.type === 'success'
                            ? 'border-green-500/20 bg-green-500/10 text-green-200'
                            : bulkStatus.type === 'warning'
                              ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                              : 'border-red-500/20 bg-red-500/10 text-red-200'
                        }`}>
                          {bulkStatus.message}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

            </div>
          )}

        </div>
        <UploadPostCalendarModal
          isOpen={isJobCalendarOpen}
          title="Job-Kalender"
          events={jobCalendarEvents}
          loading={jobCalendarLoading}
          error={jobCalendarError}
          onClose={() => setIsJobCalendarOpen(false)}
          onRefresh={() => loadJobCalendar(jobId)}
          onSaveEvent={({ event, payload }) => saveCalendarEvent({ event, payload, scope: 'job' })}
          onRescheduleEvent={({ event, payload }) => saveCalendarEvent({ event, payload: { ...payload, mode: 'recreate' }, scope: 'job' })}
          onDeleteEvent={(event) => deleteCalendarEvent(event, 'job')}
          onResolveRemotePreview={resolveCalendarRemotePreview}
          onRescheduleAll={rescheduleAllCurrentJobSocialPosts}
          showRescheduleAll
          rescheduleAllBusy={jobRescheduleAllBusy}
        />
        <UploadPostCalendarModal
          isOpen={isGlobalCalendarOpen}
          title="Upload-Post Kalender"
          events={globalCalendarEvents}
          pendingItems={globalCalendarPendingItems}
          loading={globalCalendarLoading}
          error={globalCalendarError}
          onClose={() => setIsGlobalCalendarOpen(false)}
          onRefresh={loadGlobalCalendar}
          onSaveEvent={({ event, payload }) => saveCalendarEvent({ event, payload, scope: 'global' })}
          onRescheduleEvent={({ event, payload }) => saveCalendarEvent({ event, payload: { ...payload, mode: 'recreate' }, scope: 'global' })}
          onDeleteEvent={(event) => deleteCalendarEvent(event, 'global')}
          onResolveRemotePreview={resolveCalendarRemotePreview}
          pendingSummary={{
            total_count: globalCalendarPendingItems.length,
            failed_count: globalCalendarPendingItems.filter((item) => item.status === 'failed').length,
            ready_count: globalCalendarPendingItems.filter((item) => item.status !== 'failed').length,
          }}
          defaultPostSettings={socialPostSettings}
          onSavePendingItem={saveGlobalPendingCalendarItem}
          onSchedulePendingItems={scheduleGlobalPendingCalendarItems}
          showPendingScheduler
          vendorCalendarComplete={globalCalendarVendorComplete}
          pendingOperationProgress={globalScheduleBatchProgress}
          onRepairPodcastCampaigns={repairPodcastCampaignSchedules}
          podcastCampaignRepairBusy={podcastCampaignRepairBusy}
          podcastCampaignRepairStatus={podcastCampaignRepairStatus}
        />
      </main>
    </div>
  );
}

export default App;
