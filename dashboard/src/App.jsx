import React, { useState, useEffect } from 'react';
import { Upload, FileVideo, Sparkles, Youtube, Instagram, Share2, LogOut, ChevronDown, Check, Activity, LayoutDashboard, Settings, PlusCircle, History, Menu, X, Terminal, Shield, LayoutGrid, Image, Globe, Loader2, CalendarDays, Clock3, ListFilter, GripVertical } from 'lucide-react';
import KeyInput from './components/KeyInput';
import MediaInput from './components/MediaInput';
import ResultCard from './components/ResultCard';
import ProcessingAnimation from './components/ProcessingAnimation';
// import Gallery from './components/Gallery';
import ThumbnailStudio from './components/ThumbnailStudio';
import JobHistory from './components/JobHistory';
import SocialUploadStudio from './components/SocialUploadStudio';
import { getApiUrl } from './config';
import { BACKGROUND_OPTIONS, DEFAULT_HOOK_STYLE, DEFAULT_SUBTITLE_STYLE, FONT_OPTIONS, GRID_OPTIONS, HOOK_WIDTH_OPTIONS } from './overlayOptions';
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

const buildClipSelectionKey = (activeJobId, clip, fallbackIndex) => `${activeJobId}:${clip?.clip_index ?? fallbackIndex}`;

const isClipPostedOrQueued = (clip) => {
  const status = clip?.social_post_status;
  if (!status || typeof status !== 'object') return false;

  const normalizedStatus = String(status.status || '').toLowerCase();
  const pendingCount = Number(status.pending_count || 0);
  const successCount = Number(status.success_count || 0);

  return (
    pendingCount > 0
    || successCount > 0
    || ['pending', 'in_progress', 'scheduled', 'completed', 'partial'].includes(normalizedStatus)
  );
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

const buildScheduledPostDates = ({ slotText, count, startDate, dayInterval = 1, staggerSlotsByDay = false }) => {
  const slots = parseDailyScheduleSlots(slotText, { preserveOrder: staggerSlotsByDay });
  const baseDate = new Date(`${startDate || formatDateInputValue()}T00:00:00`);
  if (Number.isNaN(baseDate.getTime())) {
    throw new Error('Ungueltiges Startdatum.');
  }
  const normalizedDayInterval = Math.max(1, Number(dayInterval) || 1);

  const now = new Date();
  const scheduledDates = [];

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
  const [pexelsKey, setPexelsKey] = useState(() => {
    const stored = localStorage.getItem('pexelsKey_v1');
    if (stored) return decrypt(stored);
    return '';
  });

  const [uploadUserId, setUploadUserId] = useState(() => localStorage.getItem('uploadUserId') || '');
  const [userProfiles, setUserProfiles] = useState([]); // List of {username, connected: []}
  const [uploadProfileStatus, setUploadProfileStatus] = useState(null); // { type: 'success' | 'error' | 'info', message: string }
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle, processing, complete, error
  const [jobState, setJobState] = useState('idle'); // queued, processing, partial, completed, failed
  const [results, setResults] = useState(null);
  const [logs, setLogs] = useState([]);
  const [logsVisible, setLogsVisible] = useState(true);
  const [processingMedia, setProcessingMedia] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard'); // dashboard, thumbnails, social-upload, history, settings
  const [historyJobs, setHistoryJobs] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [cancelingJobId, setCancelingJobId] = useState(null);
  const [deletingJobId, setDeletingJobId] = useState(null);
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
  const [clipVideoOverrides, setClipVideoOverrides] = useState({});
  const [jobOverlayDefaults, setJobOverlayDefaults] = useState({});
  const [jobSocialDefaults, setJobSocialDefaults] = useState({});

  // Sync state for original video playback
  const [syncedTime, setSyncedTime] = useState(0);
  const [isSyncedPlaying, setIsSyncedPlaying] = useState(false);
  const [syncTrigger, setSyncTrigger] = useState(0);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isMobileLiveAnalysisOpen, setIsMobileLiveAnalysisOpen] = useState(false);
  const [processingStartedAt, setProcessingStartedAt] = useState(null);
  const [clipDurationFilter, setClipDurationFilter] = useState('all');
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const [showUnpostedOnly, setShowUnpostedOnly] = useState(false);
  const [selectedClipKeys, setSelectedClipKeys] = useState([]);
  const [clipHookDrafts, setClipHookDrafts] = useState({});
  const [bulkScheduleDate, setBulkScheduleDate] = useState(() => formatDateInputValue());
  const [bulkScheduleSlots, setBulkScheduleSlots] = useState('12:00, 15:00, 18:00');
  const [bulkScheduleDayInterval, setBulkScheduleDayInterval] = useState(1);
  const [bulkScheduleStaggerSlotsByDay, setBulkScheduleStaggerSlotsByDay] = useState(false);
  const [bulkFirstComment, setBulkFirstComment] = useState('');
  const [isBulkSettingsOpen, setIsBulkSettingsOpen] = useState(false);
  const [isBulkBarCollapsed, setIsBulkBarCollapsed] = useState(false);
  const [isBulkOrderOpen, setIsBulkOrderOpen] = useState(false);
  const [isBulkScheduling, setIsBulkScheduling] = useState(false);
  const [bulkProgress, setBulkProgress] = useState(null);
  const [bulkStatus, setBulkStatus] = useState(null);
  const [draggedSelectedClipKey, setDraggedSelectedClipKey] = useState('');
  const [dragOverSelectedClipKey, setDragOverSelectedClipKey] = useState('');

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
      setShowSelectedOnly(false);
      setShowUnpostedOnly(false);
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
      setBulkFirstComment('');
      setDragOverSelectedClipKey('');
      setDraggedSelectedClipKey('');
      return;
    }

    const stored = readStoredJobUiState(jobId);
    setClipDurationFilter(stored?.clipDurationFilter || 'all');
    setShowSelectedOnly(!!stored?.showSelectedOnly);
    setShowUnpostedOnly(!!stored?.showUnpostedOnly);
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
    setBulkFirstComment(stored?.bulkFirstComment || '');
    setDraggedSelectedClipKey('');
    setDragOverSelectedClipKey('');
  }, [jobId]);

  const setOllamaModel = (value) => {
    setOllamaModelState(normalizeOllamaModelName(value));
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

  const activeJobOverlayDefaults = jobId
    ? (jobOverlayDefaults[jobId] || buildOverlayDefaultsForProfile(activeOverlayProfileId))
    : buildOverlayDefaultsForProfile(activeOverlayProfileId);
  const activeJobSocialDefaults = jobId
    ? (jobSocialDefaults[jobId] || { instagramCollaborators: '' })
    : { instagramCollaborators: '' };

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
          instagramCollaborators: prev[jobId]?.instagramCollaborators || '',
        },
      }));
      return;
    }
    setJobSocialDefaults((prev) => ({
      ...prev,
      [jobId]: {
        instagramCollaborators: persistedDefaults.instagram_collaborators || '',
      },
    }));
  }, [jobId, results?.job_social_defaults]);

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
    if (showSelectedOnly && !selectedClipKeys.includes(entry.key)) return false;
    if (showUnpostedOnly && isClipPostedOrQueued(entry.clip)) return false;
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

  useEffect(() => {
    if (!jobId) return;
    writeStoredJobUiState(jobId, {
      clipDurationFilter,
      showSelectedOnly,
      showUnpostedOnly,
      selectedClipKeys,
      clipHookDrafts,
      bulkScheduleDate,
      bulkScheduleSlots,
      bulkScheduleDayInterval,
      bulkScheduleStaggerSlotsByDay,
      bulkFirstComment,
      isBulkSettingsOpen,
      isBulkBarCollapsed,
      isBulkOrderOpen,
    });
  }, [
    jobId,
    clipDurationFilter,
    showSelectedOnly,
    showUnpostedOnly,
    selectedClipKeys,
    clipHookDrafts,
    bulkScheduleDate,
    bulkScheduleSlots,
    bulkScheduleDayInterval,
    bulkScheduleStaggerSlotsByDay,
    bulkFirstComment,
    isBulkSettingsOpen,
    isBulkBarCollapsed,
    isBulkOrderOpen,
  ]);

  let bulkSchedulePreview = [];
  let bulkSchedulePreviewError = '';
  try {
    if (selectedClipKeys.length >= 2) {
      bulkSchedulePreview = buildScheduledPostDates({
        slotText: bulkScheduleSlots,
        count: Math.min(selectedClipKeys.length, 4),
        startDate: bulkScheduleDate,
        dayInterval: bulkScheduleDayInterval,
        staggerSlotsByDay: bulkScheduleStaggerSlotsByDay,
      });
    }
  } catch (error) {
    bulkSchedulePreviewError = error.message;
  }

  const showBulkActionsBar = activeTab === 'dashboard' && status === 'complete' && selectedClipKeys.length >= 2;

  const handleBulkRenderAndSchedule = async () => {
    if (!jobId) {
      setBulkStatus({ type: 'error', message: 'Kein aktiver Job geladen.' });
      return;
    }
    if (selectedClipEntries.length < 2) {
      setBulkStatus({ type: 'error', message: 'Bitte mindestens zwei Shorts auswaehlen.' });
      return;
    }
    if (!uploadPostKey || !uploadUserId) {
      setBulkStatus({ type: 'error', message: 'Upload-Post API-Key oder Profil fehlt.' });
      return;
    }
    if (!selectedPlatformsForBulk.length) {
      setBulkStatus({ type: 'error', message: 'Bitte mindestens eine Plattform auswaehlen.' });
      return;
    }
    if (selectedPlatformsForBulk.includes('pinterest') && !(socialPostSettings.pinterestBoardId || '').trim()) {
      setBulkStatus({ type: 'error', message: 'Pinterest benoetigt eine Board-ID.' });
      return;
    }

    let scheduledDates;
    try {
      scheduledDates = buildScheduledPostDates({
        slotText: bulkScheduleSlots,
        count: selectedClipEntries.length,
        startDate: bulkScheduleDate,
        dayInterval: bulkScheduleDayInterval,
        staggerSlotsByDay: bulkScheduleStaggerSlotsByDay,
      });
    } catch (error) {
      setBulkStatus({ type: 'error', message: error.message });
      return;
    }

    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const failedSelections = [];
    const succeededSelections = [];

    setIsBulkScheduling(true);
    setBulkStatus(null);
    setIsBulkSettingsOpen(false);

    for (let position = 0; position < selectedClipEntries.length; position += 1) {
      const entry = selectedClipEntries[position];
      const hookText = String(entry.hookDraftText || '').trim();
      const clipLabel = `Clip ${entry.index + 1}`;

      if (!hookText) {
        failedSelections.push({ key: entry.key, label: clipLabel, error: 'Hook-Text ist leer.' });
        continue;
      }

      try {
        setBulkProgress({
          current: position + 1,
          total: selectedClipEntries.length,
          label: clipLabel,
          phase: 'render',
        });
        setClipHookDrafts((prev) => ({ ...prev, [entry.key]: hookText }));

        const renderRes = await fetch(getApiUrl('/api/clip/render'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            job_id: jobId,
            clip_index: entry.clip.clip_index ?? entry.index,
            apply_tight_edit: true,
            tight_edit_preset: tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset,
            apply_subtitles: true,
            subtitle_settings: buildSubtitleSettingsPayload(activeJobOverlayDefaults.subtitleStyle),
            apply_hook: true,
            hook_settings: buildHookSettingsPayload(activeJobOverlayDefaults.hookStyle, hookText),
          }),
        });

        if (!renderRes.ok) {
          throw new Error(await readErrorMessage(renderRes));
        }

        const renderData = await renderRes.json();
        const renderedClip = renderData.clip || entry.clip;
        updateClipResult(jobId, renderedClip);

        setBulkProgress({
          current: position + 1,
          total: selectedClipEntries.length,
          label: clipLabel,
          phase: 'schedule',
        });

        const postRes = await fetch(getApiUrl('/api/social/post'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            job_id: jobId,
            clip_index: renderedClip.clip_index ?? entry.index,
            api_key: uploadPostKey,
            user_id: uploadUserId,
            platforms: selectedPlatformsForBulk,
            first_comment: bulkFirstComment,
            scheduled_date: scheduledDates[position].toISOString(),
            timezone,
            instagram_share_mode: socialPostSettings.instagramShareMode,
            instagram_collaborators: String(
              renderedClip.instagram_collaborators || activeJobSocialDefaults.instagramCollaborators || ''
            ).trim() || undefined,
            tiktok_post_mode: socialPostSettings.tiktokPostMode,
            tiktok_is_aigc: socialPostSettings.tiktokIsAigc,
            facebook_page_id: socialPostSettings.facebookPageId,
            pinterest_board_id: socialPostSettings.pinterestBoardId,
          }),
        });

        if (!postRes.ok) {
          throw new Error(await readErrorMessage(postRes));
        }

        const postData = await postRes.json();
        if (postData.clip) {
          updateClipResult(jobId, postData.clip);
        }
        succeededSelections.push(entry.key);
      } catch (error) {
        failedSelections.push({
          key: entry.key,
          label: clipLabel,
          error: error.message || 'Unbekannter Fehler',
        });
      }
    }

    setIsBulkScheduling(false);
    setBulkProgress(null);

    if (failedSelections.length) {
      setSelectedClipKeys(failedSelections.map((entry) => entry.key));
      setBulkStatus({
        type: succeededSelections.length ? 'warning' : 'error',
        message: succeededSelections.length
          ? `${succeededSelections.length} Shorts geplant, ${failedSelections.length} fehlgeschlagen. ${failedSelections.slice(0, 2).map((entry) => `${entry.label}: ${entry.error}`).join(' | ')}`
          : failedSelections.slice(0, 3).map((entry) => `${entry.label}: ${entry.error}`).join(' | '),
      });
      return;
    }

    setSelectedClipKeys([]);
    setBulkStatus({
      type: 'success',
      message: `${succeededSelections.length} Shorts gerendert und fuer die naechsten Slots eingeplant.`,
    });
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
    llmProvider,
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
    youtubeAuthSettings,
  });

  const applySyncedSettings = (payload) => {
    if (!payload || typeof payload !== 'object') return;

    if (typeof payload.apiKey === 'string') setApiKey(payload.apiKey);
    if (payload.llmProvider === 'gemini' || payload.llmProvider === 'ollama') setLlmProvider(payload.llmProvider);
    if (typeof payload.ollamaBaseUrl === 'string' && payload.ollamaBaseUrl.trim()) setOllamaBaseUrl(payload.ollamaBaseUrl);
    if (typeof payload.ollamaModel === 'string' && payload.ollamaModel.trim()) setOllamaModel(payload.ollamaModel);
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
    if (payload.youtubeAuthSettings && typeof payload.youtubeAuthSettings === 'object') {
      setYoutubeAuthSettings({
        ...DEFAULT_YOUTUBE_AUTH_SETTINGS,
        ...payload.youtubeAuthSettings,
        browser: payload.youtubeAuthSettings.browser || detectLikelyBrowser(),
      });
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
    localStorage.setItem('youtube_auth_settings_v1', JSON.stringify(youtubeAuthSettings));
  }, [youtubeAuthSettings]);

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
    if (uploadPostKey && userProfiles.length === 0) {
      fetchUserProfiles();
    }
  }, [uploadPostKey]);

  useEffect(() => {
    if (activeTab === 'settings') {
      refreshYoutubeAuthStatus();
    }
  }, [activeTab]);

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

          const normalizedJobState = String(data.job_state || '').toLowerCase();

          if (data.status === 'completed' || normalizedJobState === 'completed' || normalizedJobState === 'partial') {
            setStatus('complete');
            setJobState(data.job_state || 'completed');
            clearInterval(interval);
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
    let timedOutByGuard = false;
    const failSafeTimer = window.setTimeout(() => {
      timedOutByGuard = true;
      setHistoryLoading(false);
      setHistoryError('Zeitüberschreitung beim Laden der Job-Historie. Bitte Backend-Erreichbarkeit prüfen.');
    }, 16000);
    try {
      const res = await fetchWithTimeout(
        getApiUrl('/api/jobs/history?limit=100&include_result=false&include_logs=true&log_limit=30'),
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
  }, [activeTab]);


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

  const handleProcess = async (data) => {
    const requestedProfileId = resolveProfileIdForJobRequest(!!data.options?.interviewMode);
    setStatus('processing');
    setJobState('queued');
    setLogs(["Starting process..."]);
    setResults(null);
    setClipVideoOverrides({});
    setProcessingMedia({ ...data, overlayProfileId: requestedProfileId });

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
          analysis_only: !!data.options?.analysisOnly,
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
      setJobId(resData.job_id);
      ensureJobOverlayDefaults(resData.job_id, requestedProfileId, true);
      fetchJobHistory();

    } catch (e) {
      setStatus('error');
      setJobState('failed');
      setLogs(l => [...l, `Fehler beim Starten des Jobs: ${e.message}`]);
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
      const requestMeta = job?.request || {};
      const profileIdForJob = resolveProfileIdForJobRequest(!!requestMeta.interview_mode);
      setJobId(job.job_id);
      setResults(data.result || job.result || null);
      setLogs(data.logs || job.logs || []);
      setProcessingMedia(deriveProcessingMedia(job));
      ensureJobOverlayDefaults(job.job_id, profileIdForJob);
      setJobState(data.job_state || job.status || 'completed');
      setStatus(mapApiStatusToUi(data.status));
      setActiveTab('dashboard');
    } catch (e) {
      alert(`Job konnte nicht geöffnet werden: ${e.message}`);
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

            {llmProvider === 'gemini' && !apiKey && (
              <span className="text-xs text-amber-500 bg-amber-500/10 px-3 py-1 rounded-full border border-amber-500/20">
                API-Key fehlt
              </span>
            )}
          </div>
        </header>

        {/* Main Workspace */}
        <div className="flex-1 min-h-0 overflow-hidden relative">

          {activeTab === 'history' && (
            <JobHistory
              jobs={historyJobs}
              loading={historyLoading}
              error={historyError}
              currentJobId={jobId}
              cancelingJobId={cancelingJobId}
              deletingJobId={deletingJobId}
              onRefresh={fetchJobHistory}
              onOpenJob={handleOpenJob}
              onResumeJob={handleResumeJob}
              onCancelJob={handleCancelJob}
              onDeleteJob={handleDeleteJob}
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
                  <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-zinc-500 uppercase tracking-wider">Verschlüsselt</span>
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
            <div className="h-full min-h-0 flex flex-col md:flex-row animate-[fadeIn_0.3s_ease-out]">

              {/* Left Panel: Preview & Status */}
              <div className={`${status === 'complete' ? 'w-full md:w-[30%] lg:w-[25%]' : 'w-full md:w-[55%] lg:w-[60%]'} md:h-full ${isMobileLiveAnalysisOpen ? 'h-[44dvh]' : 'h-auto'} md:max-h-none flex flex-col border-b md:border-b-0 md:border-r border-white/5 bg-black/20 p-4 md:p-6 overflow-hidden md:overflow-y-auto custom-scrollbar touch-scroll transition-all duration-700 ease-in-out`}>
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

                <div className={`${isMobileLiveAnalysisOpen ? 'flex' : 'hidden'} md:flex flex-1 min-h-0 flex-col gap-4`}>
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
              <div className={`${status === 'complete' ? 'w-full md:w-[70%] lg:w-[75%]' : 'w-full md:w-[45%] lg:w-[40%]'} flex-1 min-h-0 md:h-full flex flex-col bg-background p-4 md:p-6 transition-all duration-700 ease-in-out`}>
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

                  {bulkStatus?.message && !showBulkActionsBar && (
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

                <div className={`flex-1 min-h-0 overflow-y-auto custom-scrollbar touch-scroll p-1 ${
                  showBulkActionsBar
                    ? (isBulkBarCollapsed ? 'pb-32 md:pb-28' : 'pb-[30rem] md:pb-[24rem]')
                    : ''
                }`}>
                  {results && results.clips && results.clips.length > 0 ? (
                    filteredClipEntries.length > 0 ? (
                    <div className={`grid gap-4 pb-10 ${status === 'complete' ? 'grid-cols-1 xl:grid-cols-2' : 'grid-cols-1'}`}>
                      {filteredClipEntries.map(({ clip, index: i, key, hookDraftText }) => (
                        <ResultCard
                          key={key}
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
                          subtitleStyle={activeJobOverlayDefaults.subtitleStyle}
                          hookStyle={activeJobOverlayDefaults.hookStyle}
                          tightEditPreset={tightEditSettings.preset || DEFAULT_TIGHT_EDIT_SETTINGS.preset}
                          socialPostSettings={socialPostSettings}
                          jobInstagramCollaborators={activeJobSocialDefaults.instagramCollaborators}
                          activeUploadProfile={uploadUserId}
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
                            : showUnpostedOnly
                              ? 'Kein Clip passt zum Filter Nicht gepostet.'
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
                              {selectedClipKeys.length} Shorts ausgewaehlt
                            </span>
                            {bulkProgress && (
                              <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-cyan-200">
                              {bulkProgress.current}/{bulkProgress.total} {bulkProgress.phase === 'render' ? 'Render' : 'Schedule'}
                              </span>
                            )}
                          </div>
                          <p className="mt-2 text-xs text-zinc-400">
                            {isBulkBarCollapsed
                              ? 'Multi-Post-Leiste minimiert. Erweitern, um Reihenfolge, Timing und Posting-Optionen zu bearbeiten.'
                              : 'Quick-Render nutzt globale Untertitel- und Hook-Vorgaben. Die Reihenfolge-Liste bestimmt die Posting-Reihenfolge.'}
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setIsBulkOrderOpen((prev) => !prev)}
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
                            disabled={isBulkScheduling}
                            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-300 hover:bg-white/10 disabled:opacity-50"
                          >
                            <X size={15} />
                            Auswahl leeren
                          </button>
                          <button
                            type="button"
                            onClick={handleBulkRenderAndSchedule}
                            disabled={isBulkScheduling}
                            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-fuchsia-600 to-pink-600 px-4 py-2.5 text-sm font-semibold text-white hover:from-fuchsia-500 hover:to-pink-500 disabled:opacity-60"
                          >
                            {isBulkScheduling ? <Loader2 size={16} className="animate-spin" /> : <Share2 size={16} />}
                            {isBulkScheduling ? 'Bearbeite Auswahl...' : 'Rendern & planen'}
                          </button>
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
                        <div className="grid gap-3 md:grid-cols-[180px_140px_minmax(0,1fr)] xl:grid-cols-[180px_140px_minmax(0,1fr)_minmax(0,1fr)]">
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
      </main>
    </div>
  );
}

export default App;
