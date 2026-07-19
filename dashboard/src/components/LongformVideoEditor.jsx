import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Clapperboard,
  Clock3,
  Download,
  Film,
  GripVertical,
  HelpCircle,
  Image,
  Loader2,
  PauseCircle,
  PlayCircle,
  Plus,
  RefreshCcw,
  RotateCcw,
  Save,
  Shuffle,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react';
import { getApiUrl } from '../config';

const STORAGE_KEY = 'openshorts_longform_selected_project_v1';

const DEFAULT_CONFIG = {
  preset: 'balanced',
  primary_audio_camera: 'single',
  cfr_transcode_enabled: false,
  proxy_enabled: false,
  analysis_language: 'de',
  export_fps: 24,
  min_shot_length_sec: 3,
  speaker_switch_hold_ms: 900,
  long_pause_threshold_ms: 650,
  pause_trim_target_ms: 260,
  filler_word_cut_level: 1,
  remove_umms: false,
  backchannel_max_duration_ms: 700,
  backchannel_max_words: 3,
  reaction_marker_enabled: true,
  retake_mode: 'aggressive_cut',
  jcut_enabled: true,
  lcut_enabled: true,
  pyannote_diarization_enabled: true,
  export_loudness_adjustment_enabled: false,
  export_primary_audio_stereo_enabled: true,
  review_threshold: 0.62,
  thumbnail_prompt_preset_id: '',
  thumbnail_prompt_text: '',
  thumbnail_feedback_text: '',
  thumbnail_text_overlay_text: '',
  thumbnail_text_overlay_suggestions: [],
  thumbnail_provider_selection: ['gemini'],
  thumbnail_variations: 3,
  thumbnail_reference_role_order: 'host_guest',
  thumbnail_selected_stills: {},
  thumbnail_provider_models: {
    gemini: 'gemini-2.5-flash-image',
    openai: 'gpt-image-1',
    midjourney: 'auto',
  },
};

const DEFAULT_AI = {
  provider: 'ollama',
  ollama_base_url: 'http://127.0.0.1:11434',
  ollama_model: 'gemma3:12b',
  gemini_api_key: '',
  gemini_model: 'gemini-2.5-flash',
  huggingface_token: '',
  openai_api_key: '',
  openai_model: 'gpt-4.1-mini',
  claude_api_key: '',
  claude_model: 'claude-3-5-sonnet-latest',
  minimax_api_key: '',
  minimax_auth_mode: 'token_plan',
  minimax_model: 'MiniMax-M3',
  midjourney_api_key: '',
  midjourney_base_url: '',
};

const DEFAULT_THUMBNAIL_MODEL_DEFAULTS = {
  gemini: 'gemini-3.1-flash-image',
  openai: 'gpt-image-1',
  midjourney: 'auto',
};

const THUMBNAIL_MODEL_SUGGESTIONS = {
  gemini: ['gemini-3.1-flash-image', 'gemini-3.1-flash-image-preview', 'gemini-3-pro-image-preview', 'gemini-2.5-flash-image', 'auto'],
  openai: ['gpt-image-1'],
  midjourney: ['auto', 'v7', 'v6.1', 'niji 6'],
};

const STATUS_STYLES = {
  idle: 'border-white/10 bg-white/5 text-zinc-300',
  queued: 'border-zinc-500/20 bg-zinc-500/10 text-zinc-200',
  processing: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100',
  paused: 'border-amber-500/20 bg-amber-500/10 text-amber-100',
  completed: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100',
  failed: 'border-red-500/20 bg-red-500/10 text-red-200',
  stopped: 'border-orange-500/20 bg-orange-500/10 text-orange-200',
};

const ROLE_LABELS = {
  single: 'Kamera',
  host: 'Host',
  guest: 'Gast',
};

const FIELD_HINTS = {
  project_name: 'Nur der interne Projektname im Dashboard. Er aendert keine Dateinamen oder Exporte.',
  mode: 'Single Camera fuer einen Hauptwinkel. Interview fuer Host/Gast mit getrennten Rollen, Sync und Sprecherlogik.',
  preset: 'Startpunkt fuer die Schnittlogik. Conservative schneidet am wenigsten, Aggressive schaltet schneller und kuerzt staerker.',
  primary_audio_camera: 'Diese Spur ist die Referenz fuer Sync, Transkription und Pausenanalyse. Waehle die sauberste Mikrofonspur.',
  cfr_transcode_enabled: 'Optionaler technischer Sicherheitsmodus. Er erzeugt eine neue CFR-Arbeitskopie nur dann, wenn du problematisches Material wie Handy-, Screen- oder Webcam-Dateien stabilisieren willst. Aus spart Speicher und laesst XML direkt auf die Originaldateien zeigen.',
  proxy_enabled: 'Erzeugt kleinere 720p-Dateien fuer fluessigeres Review in Resolve. Der finale Export bleibt davon unberuehrt.',
  reaction_marker_enabled: 'Markiert brauchbare Reaktionen des Gegenuebers wie Nicken, Lachen oder kurze Antworten fuer spaetere Cutaways.',
  remove_umms: 'Entfernt Fuelllaute wie aeh oder aehm nur vorsichtig. Standard ist aus, damit nichts versehentlich ueberstrafft wird.',
  jcut_enabled: 'Das Audio des naechsten Sprechers darf minimal frueher beginnen als der Bildschnitt. Macht Gespraeche oft flüssiger.',
  lcut_enabled: 'Das Audio des aktuellen Sprechers darf minimal ueber den Bildschnitt hinaus weiterlaufen. Hilft bei weicheren Wechseln.',
  pyannote_diarization_enabled: 'Nutze optional pyannote fuer robustere Sprecherwechsel. Wenn pyannote im Backend nicht installiert oder nicht konfiguriert ist, faellt OpenShorts automatisch auf die vorhandene Audio-Logik zurueck.',
  export_loudness_adjustment_enabled: 'Schreibt Lautheitsanpassungen als adjust-volume in die FCPXML. Standardmaessig aus.',
  export_primary_audio_stereo_enabled: 'Exportiert zusaetzlich das gewaehlte Hauptaudio als Stereo-WAV sowie linke und rechte Kanal-Stems fuer Download und Referenz.',
  export_fps: 'Zielframerate der Rough-Cut-Timeline und des FCPXML. In Deutschland oft 25, bei Social/US-Quellen haeufig 30.',
  min_shot_length_sec: 'Minimale Bildlaenge, bevor wieder umgeschnitten werden darf. Hoeher = ruhiger, niedriger = dynamischer.',
  speaker_switch_hold_ms: 'Wie lange ein anderer Sprecher dominieren muss, bevor die Kamera wirklich umspringt. Verhindert hektisches Hin-und-her.',
  long_pause_threshold_ms: 'Ab welcher Pausenlaenge OpenShorts die Stille als kuerzbaren Leerlauf behandelt.',
  pause_trim_target_ms: 'Wie viel Restpause nach dem Kuerzen stehen bleiben soll. 0 = sehr hart, hoeher = natuerlicher.',
  filler_word_cut_level: 'Wie offensiv Fuellwoerter wie aeh, also oder quasi entfernt werden. Aggressiver kann natuerlicheres Sprechen auch beschaedigen.',
  backchannel_max_duration_ms: 'Maximale Dauer fuer kurze Einwuerfe wie mhm, ja, genau, die eher als Reaktion als als eigener Turn gelten.',
  backchannel_max_words: 'Wortgrenze fuer solche kurzen Einwuerfe. Hoeher = mehr Segmente werden als Backchannel erkannt.',
  review_threshold: 'Alles unter diesem Sicherheitswert wird lieber als Review-Marker markiert statt stillschweigend hart entschieden. Hoeher = mehr manuelle Pruefpunkte.',
  retake_mode: 'Mark: nur kennzeichnen. Conservative Cut: klares Retake-Praefix wird vorsichtig vorne abgeschnitten. Aggressive Cut schneidet bei eindeutigen Retake-Cues deutlich entschlossener. Off: ignorieren.',
  analysis_language: 'Sprachhinweis fuer Whisper und Analyse. Zum Beispiel de, en oder auto-nahe Codes wie de.',
};

const STEP_HINTS = {
  ingest: 'Bereitet das Rohmaterial technisch vor: Dateien einlesen, bei Bedarf in konstante FPS umwandeln, Audio extrahieren und optional Proxies erzeugen. Ziel ist sauberes, stabil analysierbares Material.',
  sync: 'Gleicht mehrere Kameras oder Recorder zeitlich aneinander an. Dabei werden Audioverlaeufe verglichen, damit Host-, Gast- und Zusatzkameras spaeter an den richtigen Stellen zusammenpassen.',
  transcription: 'Erstellt mit Whisper die Transkripte der Quelldateien. Diese Texte bilden die Grundlage fuer Sprecherwechsel, Pausenanalyse, Review-Marker und spaetere Schnittentscheidungen.',
  analysis: 'Wertet Transkript, Timing und Struktur aus. Hier entstehen konservative Schnittvorschlaege, Backchannel-Erkennung, Reaktionsmarker, Retake-Hinweise und die eigentliche Rough-Cut-Logik.',
  export: 'Schreibt die Ergebnisse in editierbare Artefakte wie FCPXML, JSON und Marker-Dateien, damit du den Rohschnitt in Resolve oder aehnlichen Tools weiterbearbeiten kannst.',
};

const TOGGLE_OPTIONS = [
  ['cfr_transcode_enabled', 'Normalisierung (CFR)', 'Nur bei problematischen Quellen aktivieren.'],
  ['proxy_enabled', 'Proxies', '720p Proxies fuer fluessigeres Review.'],
  ['reaction_marker_enabled', 'Reaction Marker', 'Interessante Zuhoerer-Momente markieren.'],
  ['remove_umms', 'Umms entfernen', 'Standard ist aus. Nur aktivieren, wenn du bewusst mehr sprachlich straffen willst.'],
  ['jcut_enabled', 'J-Cut lite', 'Minimale visuelle Vorverlagerung.'],
  ['lcut_enabled', 'L-Cut lite', 'Minimale visuelle Nachlauf-Regel.'],
  ['pyannote_diarization_enabled', 'Pyannote Diarization', 'Optional und fallback-sicher.'],
  ['export_loudness_adjustment_enabled', 'Lautheit exportieren', 'Standardmaessig aus.'],
  ['export_primary_audio_stereo_enabled', 'Stereo-Hauptaudio exportieren', 'Stereo plus linke/rechte Stems.'],
];

const activeRolesForMode = (mode) => (mode === 'interview' ? ['host', 'guest'] : ['single']);

const clampNumber = (value, fallback) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const normalizeThumbnailProviderModels = (value, defaults = DEFAULT_THUMBNAIL_MODEL_DEFAULTS) => {
  const source = value && typeof value === 'object' ? value : {};
  const normalizeGeminiModel = (model) => {
    const normalized = String(model || '').trim();
    if (!normalized) return DEFAULT_THUMBNAIL_MODEL_DEFAULTS.gemini;
    if (normalized === 'gemini-2.5-flash') {
      return 'gemini-2.5-flash-image';
    }
    if (['gemini-3.1-flash-image-preview', 'gemini-3-pro-image-preview', 'gemini-2.5-flash-image'].includes(normalized)) {
      return normalized;
    }
    return normalized;
  };
  return {
    gemini: normalizeGeminiModel(source.gemini || defaults.gemini || DEFAULT_THUMBNAIL_MODEL_DEFAULTS.gemini),
    openai: String(source.openai || defaults.openai || DEFAULT_THUMBNAIL_MODEL_DEFAULTS.openai).trim() || DEFAULT_THUMBNAIL_MODEL_DEFAULTS.openai,
    midjourney: String(source.midjourney || defaults.midjourney || DEFAULT_THUMBNAIL_MODEL_DEFAULTS.midjourney).trim() || DEFAULT_THUMBNAIL_MODEL_DEFAULTS.midjourney,
  };
};

const getThumbnailProviderRuntimeStatus = (provider, runtimeAi) => {
  const normalizedProvider = String(provider || '').trim().toLowerCase();
  if (normalizedProvider === 'gemini') {
    return {
      available: !!String(runtimeAi?.gemini_api_key || '').trim(),
      label: String(runtimeAi?.gemini_api_key || '').trim() ? 'Gemini-Key vorhanden' : 'Gemini-Key fehlt',
    };
  }
  if (normalizedProvider === 'openai') {
    return {
      available: !!String(runtimeAi?.openai_api_key || '').trim(),
      label: String(runtimeAi?.openai_api_key || '').trim() ? 'OpenAI-Key vorhanden' : 'OpenAI-Key fehlt',
    };
  }
  if (normalizedProvider === 'midjourney') {
    const hasBridge = !!String(runtimeAi?.midjourney_base_url || '').trim();
    return {
      available: hasBridge,
      label: hasBridge ? 'Midjourney-Bridge vorhanden' : 'Midjourney-Bridge fehlt',
    };
  }
  return { available: false, label: 'Konfiguration fehlt' };
};

const sanitizeProjectAiConfig = (value) => ({
  provider: String(value?.provider || DEFAULT_AI.provider).trim() || DEFAULT_AI.provider,
  ollama_base_url: String(value?.ollama_base_url || DEFAULT_AI.ollama_base_url).trim() || DEFAULT_AI.ollama_base_url,
  ollama_model: String(value?.ollama_model || DEFAULT_AI.ollama_model).trim() || DEFAULT_AI.ollama_model,
});

const mergeRuntimeAi = (globalAiDefaults, projectAi) => ({
  ...DEFAULT_AI,
  ...(globalAiDefaults || {}),
  ...sanitizeProjectAiConfig(projectAi || {}),
  gemini_api_key: String(globalAiDefaults?.gemini_api_key || '').trim(),
  huggingface_token: String(globalAiDefaults?.huggingface_token || '').trim(),
  openai_api_key: String(globalAiDefaults?.openai_api_key || '').trim(),
  claude_api_key: String(globalAiDefaults?.claude_api_key || '').trim(),
  minimax_api_key: String(globalAiDefaults?.minimax_api_key || '').trim(),
  midjourney_api_key: String(globalAiDefaults?.midjourney_api_key || '').trim(),
  midjourney_base_url: String(globalAiDefaults?.midjourney_base_url || '').trim(),
});

const readErrorMessage = async (res) => {
  const text = await res.text();
  try {
    const json = JSON.parse(text);
    return json.detail || json.message || text;
  } catch {
    return text;
  }
};

const formatTimestamp = (value) => {
  if (!value) return '—';
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value * 1000));
  } catch {
    return '—';
  }
};

const formatBytes = (value) => {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let current = bytes;
  let index = 0;
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024;
    index += 1;
  }
  const precision = current >= 10 || index === 0 ? 0 : 1;
  return `${current.toFixed(precision)} ${units[index]}`;
};

const formatDuration = (value) => {
  const totalSeconds = Number(value);
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return '—';
  const rounded = Math.round(totalSeconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const seconds = rounded % 60;
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
};

const normalizeTextOverlaySuggestions = (value) => {
  const source = Array.isArray(value) ? value : [];
  const next = [];
  source.forEach((item) => {
    const text = String(item || '').trim();
    if (!text || next.includes(text)) return;
    next.push(text.slice(0, 80));
  });
  return next.slice(0, 10);
};

const injectTextOverlayIntoPrompt = (prompt, textOverlay) => {
  const basePrompt = String(prompt || '');
  const overlay = String(textOverlay || '').trim();
  if (!basePrompt.includes('<text_overlay>')) return basePrompt;
  return basePrompt.replaceAll('<text_overlay>', overlay);
};

function FileUploadButton({ role, busy, onUpload }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200 hover:bg-white/10">
      {busy ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
      Dateien hinzufügen
      <input
        type="file"
        multiple
        accept="video/*,audio/*"
        className="hidden"
        onChange={(event) => {
          const nextFiles = Array.from(event.target.files || []);
          event.target.value = '';
          if (nextFiles.length) {
            onUpload(role, nextFiles);
          }
        }}
      />
    </label>
  );
}

function HintBadge({ hint }) {
  if (!hint) return null;
  return (
    <span
      className="group relative inline-flex cursor-help items-center text-zinc-500 outline-none"
      tabIndex={0}
      title={hint}
      aria-label={hint}
    >
      <HelpCircle size={14} />
      <span className="pointer-events-none absolute left-0 top-full z-20 mt-2 w-72 rounded-xl border border-white/10 bg-zinc-950/95 px-3 py-2 text-[11px] leading-relaxed text-zinc-200 opacity-0 shadow-2xl transition-opacity duration-150 group-hover:opacity-100 group-focus:opacity-100">
        {hint}
      </span>
    </span>
  );
}

function FieldLabel({ label, hint }) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <span className="block text-sm text-zinc-400">{label}</span>
      <HintBadge hint={hint} />
    </div>
  );
}

export default function LongformVideoEditor({ globalAiDefaults = null, thumbnailPromptPresets = [], thumbnailModelDefaults = null, onSaveAiDefaults = null }) {
  const resolvedGlobalAiDefaults = useMemo(
    () => ({ ...DEFAULT_AI, ...(globalAiDefaults || {}) }),
    [globalAiDefaults],
  );
  const resolvedThumbnailModelDefaults = useMemo(
    () => normalizeThumbnailProviderModels(thumbnailModelDefaults, DEFAULT_THUMBNAIL_MODEL_DEFAULTS),
    [thumbnailModelDefaults],
  );
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState(() => localStorage.getItem(STORAGE_KEY) || '');
  const [projectBundle, setProjectBundle] = useState(null);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingBundle, setLoadingBundle] = useState(false);
  const [busyAction, setBusyAction] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [infoMessage, setInfoMessage] = useState('');
  const [dragState, setDragState] = useState({ role: '', fileId: '' });
  const [mountedPathDrafts, setMountedPathDrafts] = useState({ single: '', host: '', guest: '' });
  const [mountedSearchQueries, setMountedSearchQueries] = useState({ single: '', host: '', guest: '' });
  const [mountedSearchResults, setMountedSearchResults] = useState({ single: [], host: [], guest: [] });
  const [mountedSearchBusy, setMountedSearchBusy] = useState({ single: false, host: false, guest: false });
  const [mountedSearchFeedback, setMountedSearchFeedback] = useState({ single: null, host: null, guest: null });
  const [selectedStillByRole, setSelectedStillByRole] = useState({});
  const [loadingSpeakerStills, setLoadingSpeakerStills] = useState(false);
  const [generatingThumbnails, setGeneratingThumbnails] = useState(false);
  const [generatingOverlaySuggestions, setGeneratingOverlaySuggestions] = useState(false);
  const [hoveredStill, setHoveredStill] = useState(null);

  const [createName, setCreateName] = useState('Neues Podcast-Projekt');
  const [createMode, setCreateMode] = useState('single');

  const [draftProjectName, setDraftProjectName] = useState('');
  const [draftMode, setDraftMode] = useState('single');
  const [draftConfig, setDraftConfig] = useState(DEFAULT_CONFIG);
  const [draftAi, setDraftAi] = useState(DEFAULT_AI);

  const selectedProject = projectBundle?.project || null;
  const selectedState = projectBundle?.state || null;
  const selectedLogs = projectBundle?.logs || [];
  const roles = useMemo(() => activeRolesForMode(draftMode), [draftMode]);
  const availableThumbnailPromptPresets = useMemo(() => Array.isArray(thumbnailPromptPresets) ? thumbnailPromptPresets.filter((item) => item?.name && item?.prompt) : [], [thumbnailPromptPresets]);
  const savedProjectSnapshot = useMemo(() => {
    if (!selectedProject) return null;
    return {
      project_name: selectedProject.project_name || '',
      mode: selectedProject.mode || 'single',
      config: {
        ...DEFAULT_CONFIG,
        ...(selectedProject.config || {}),
        thumbnail_text_overlay_suggestions: normalizeTextOverlaySuggestions(selectedProject?.config?.thumbnail_text_overlay_suggestions),
        thumbnail_provider_models: normalizeThumbnailProviderModels(
          selectedProject?.config?.thumbnail_provider_models,
          resolvedThumbnailModelDefaults,
        ),
      },
      ai: sanitizeProjectAiConfig(selectedProject.ai || {}),
    };
  }, [resolvedThumbnailModelDefaults, selectedProject]);
  const draftProjectSnapshot = useMemo(() => ({
    project_name: draftProjectName || '',
    mode: draftMode || 'single',
    config: {
      ...DEFAULT_CONFIG,
      ...(draftConfig || {}),
      thumbnail_text_overlay_suggestions: normalizeTextOverlaySuggestions(draftConfig?.thumbnail_text_overlay_suggestions),
      thumbnail_provider_models: normalizeThumbnailProviderModels(
        draftConfig?.thumbnail_provider_models,
        resolvedThumbnailModelDefaults,
      ),
    },
    ai: sanitizeProjectAiConfig(draftAi || {}),
  }), [draftAi, draftConfig, draftMode, draftProjectName, resolvedThumbnailModelDefaults]);
  const effectiveRuntimeAi = useMemo(
    () => mergeRuntimeAi(resolvedGlobalAiDefaults, draftAi || {}),
    [draftAi, resolvedGlobalAiDefaults],
  );
  const hasUnsavedProjectChanges = useMemo(() => {
    if (!savedProjectSnapshot) return false;
    return JSON.stringify(draftProjectSnapshot) !== JSON.stringify(savedProjectSnapshot);
  }, [draftProjectSnapshot, savedProjectSnapshot]);

  const fetchProjects = async () => {
    setLoadingProjects(true);
    try {
      const res = await fetch(getApiUrl('/api/longform/projects'));
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const nextProjects = data.projects || [];
      setProjects(nextProjects);
      if (!selectedProjectId && nextProjects[0]?.project_id) {
        setSelectedProjectId(nextProjects[0].project_id);
      }
    } catch (error) {
      setErrorMessage(error.message || 'Longform-Projekte konnten nicht geladen werden.');
    } finally {
      setLoadingProjects(false);
    }
  };

  const fetchProjectBundle = async (projectId) => {
    if (!projectId) {
      setProjectBundle(null);
      return;
    }
    setLoadingBundle(true);
    try {
      const res = await fetch(getApiUrl(`/api/longform/projects/${projectId}`));
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      setErrorMessage('');
    } catch (error) {
      setErrorMessage(error.message || 'Projekt konnte nicht geladen werden.');
    } finally {
      setLoadingBundle(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  useEffect(() => {
    if (!infoMessage) return undefined;
    const timer = window.setTimeout(() => setInfoMessage(''), 2800);
    return () => window.clearTimeout(timer);
  }, [infoMessage]);

  useEffect(() => {
    if (!selectedProjectId) return;
    localStorage.setItem(STORAGE_KEY, selectedProjectId);
    fetchProjectBundle(selectedProjectId);
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedProject) return;
    const mergedConfig = {
      ...DEFAULT_CONFIG,
      ...(selectedProject.config || {}),
      thumbnail_text_overlay_suggestions: normalizeTextOverlaySuggestions(selectedProject?.config?.thumbnail_text_overlay_suggestions),
    };
    if (!mergedConfig.thumbnail_prompt_text && availableThumbnailPromptPresets[0]?.prompt) {
      mergedConfig.thumbnail_prompt_text = availableThumbnailPromptPresets[0].prompt;
      mergedConfig.thumbnail_prompt_preset_id = availableThumbnailPromptPresets[0].id;
    }
    if (!Array.isArray(mergedConfig.thumbnail_provider_selection) || !mergedConfig.thumbnail_provider_selection.length) {
      mergedConfig.thumbnail_provider_selection = ['gemini'];
    }
    mergedConfig.thumbnail_provider_models = normalizeThumbnailProviderModels(
      mergedConfig.thumbnail_provider_models,
      resolvedThumbnailModelDefaults,
    );
    setDraftProjectName(selectedProject.project_name || '');
    setDraftMode(selectedProject.mode || 'single');
    setDraftConfig(mergedConfig);
    setDraftAi(mergeRuntimeAi(resolvedGlobalAiDefaults, selectedProject.ai || {}));
  }, [availableThumbnailPromptPresets, resolvedGlobalAiDefaults, resolvedThumbnailModelDefaults, selectedProject]);

  useEffect(() => {
    const stillsByRole = selectedProject?.artifacts?.speaker_stills || {};
    const configured = selectedProject?.config?.thumbnail_selected_stills || {};
    const nextSelection = { ...configured };
    Object.entries(stillsByRole).forEach(([role, items]) => {
      if (!nextSelection[role] && items?.[0]?.path) {
        nextSelection[role] = items[0].path;
      }
    });
    setSelectedStillByRole(nextSelection);
  }, [selectedProject?.artifacts?.speaker_stills, selectedProject?.config?.thumbnail_selected_stills]);

  const refreshAll = async () => {
    await fetchProjects();
    if (selectedProjectId) {
      await fetchProjectBundle(selectedProjectId);
    }
  };

  const handleCreateProject = async () => {
    setBusyAction('create');
    try {
      const res = await fetch(getApiUrl('/api/longform/projects'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_name: createName,
          mode: createMode,
          config: {
            ...DEFAULT_CONFIG,
            primary_audio_camera: createMode === 'interview' ? 'host' : 'single',
            thumbnail_prompt_preset_id: availableThumbnailPromptPresets[0]?.id || '',
            thumbnail_prompt_text: availableThumbnailPromptPresets[0]?.prompt || '',
            thumbnail_provider_selection: ['gemini'],
            thumbnail_variations: 3,
            thumbnail_provider_models: resolvedThumbnailModelDefaults,
          },
          ai: sanitizeProjectAiConfig(resolvedGlobalAiDefaults),
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setSelectedProjectId(data.project.project_id);
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      await fetchProjects();
      setErrorMessage('');
    } catch (error) {
      setErrorMessage(error.message || 'Projekt konnte nicht erstellt werden.');
    } finally {
      setBusyAction('');
    }
  };

  const persistProjectDraft = async ({ showSavingState = false, includeRuntimeSecrets = false } = {}) => {
    if (!selectedProject) return;
    if (showSavingState) {
      setBusyAction('save');
    }
    try {
      const res = await fetch(getApiUrl(`/api/longform/projects/${selectedProject.project_id}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_name: draftProjectName,
          mode: draftMode,
          config: {
            ...draftConfig,
            thumbnail_text_overlay_suggestions: normalizeTextOverlaySuggestions(draftConfig?.thumbnail_text_overlay_suggestions),
            thumbnail_provider_models: normalizeThumbnailProviderModels(
              draftConfig?.thumbnail_provider_models,
              resolvedThumbnailModelDefaults,
            ),
          },
          ai: includeRuntimeSecrets ? effectiveRuntimeAi : sanitizeProjectAiConfig(effectiveRuntimeAi),
        }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      await fetchProjects();
      setErrorMessage('');
      return data;
    } catch (error) {
      const message = error.message || 'Projekt konnte nicht gespeichert werden.';
      setErrorMessage(message);
      throw error instanceof Error ? error : new Error(message);
    } finally {
      if (showSavingState) {
        setBusyAction('');
      }
    }
  };

  const handleSaveProject = async () => {
    try {
      await persistProjectDraft({ showSavingState: true });
    } catch {
      // persistProjectDraft already surfaced the error
    }
  };

  const handleSaveAiDefaults = () => {
    if (typeof onSaveAiDefaults !== 'function') return;
    onSaveAiDefaults(sanitizeProjectAiConfig(draftAi));
    setInfoMessage('Longform-KI-Standards aktualisiert.');
    setErrorMessage('');
  };

  const handleUploadRoleFiles = async (role, nextFiles) => {
    if (!selectedProject) return;
    setBusyAction(`upload:${role}`);
    try {
      const formData = new FormData();
      formData.append('role', role);
      nextFiles.forEach((file) => formData.append('files', file));
      const res = await fetch(getApiUrl(`/api/longform/projects/${selectedProject.project_id}/files`), {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      await fetchProjects();
      setErrorMessage('');
    } catch (error) {
      setErrorMessage(error.message || 'Dateien konnten nicht hochgeladen werden.');
    } finally {
      setBusyAction('');
    }
  };

  const handleImportMountedPaths = async (role) => {
    if (!selectedProject) return;
    const rawInput = mountedPathDrafts[role] || '';
    const sourcePaths = rawInput
      .split(/[\n;,]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!sourcePaths.length) {
      setErrorMessage('Bitte mindestens einen Dateipfad angeben.');
      return;
    }

    setBusyAction(`import:${role}`);
    try {
      const res = await fetch(getApiUrl(`/api/longform/projects/${selectedProject.project_id}/files/by-path`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role, source_paths: sourcePaths }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      setMountedPathDrafts((prev) => ({ ...prev, [role]: '' }));
      setMountedSearchQueries((prev) => ({ ...prev, [role]: '' }));
      setMountedSearchResults((prev) => ({ ...prev, [role]: [] }));
      setMountedSearchFeedback((prev) => ({ ...prev, [role]: null }));
      await fetchProjects();
      setErrorMessage('');
    } catch (error) {
      setErrorMessage(error.message || 'Dateien konnten nicht per Pfad eingebunden werden.');
    } finally {
      setBusyAction('');
    }
  };

  const appendMountedPath = (role, nextPath) => {
    setMountedPathDrafts((prev) => {
      const currentItems = String(prev[role] || '')
        .split(/[\n;,]+/)
        .map((item) => item.trim())
        .filter(Boolean);
      if (!currentItems.includes(nextPath)) {
        currentItems.push(nextPath);
      }
      return {
        ...prev,
        [role]: currentItems.join('\n'),
      };
    });
  };

  const handleSearchMountedFiles = async (role) => {
    const query = String(mountedSearchQueries[role] || '').trim();
    if (!query) {
      setMountedSearchResults((prev) => ({ ...prev, [role]: [] }));
      setMountedSearchFeedback((prev) => ({ ...prev, [role]: null }));
      return;
    }

    setMountedSearchBusy((prev) => ({ ...prev, [role]: true }));
    try {
      const res = await fetch(getApiUrl(`/api/longform/source-files/search?q=${encodeURIComponent(query)}&limit=30`));
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const nextResults = Array.isArray(data.results) ? data.results : [];
      const searchedRoots = Array.isArray(data.searched_roots) ? data.searched_roots.filter(Boolean) : [];
      const rootsLabel = searchedRoots.length ? searchedRoots.join(', ') : 'keine freigegebenen Roots';
      setMountedSearchResults((prev) => ({ ...prev, [role]: nextResults }));
      setMountedSearchFeedback((prev) => ({
        ...prev,
        [role]: nextResults.length
          ? {
            type: 'success',
            message: `${nextResults.length} Treffer in ${rootsLabel}`,
          }
          : {
            type: 'info',
            message: data.mount_has_media
              ? `Keine Treffer fuer "${query}" in ${rootsLabel}.`
              : `Im Container sind aktuell keine Longform-Dateien unter ${rootsLabel} sichtbar. Wenn der Datentraeger auf dem Host korrekt gemountet ist, brauchst du nach neuem Remount meist ein Docker-Recreate mit dem aktualisierten Bind-Mount.`,
          },
      }));
      setErrorMessage('');
    } catch (error) {
      setErrorMessage(error.message || 'Dateisuche auf dem Mount fehlgeschlagen.');
      setMountedSearchFeedback((prev) => ({ ...prev, [role]: null }));
    } finally {
      setMountedSearchBusy((prev) => ({ ...prev, [role]: false }));
    }
  };

  const handleDeleteFile = async (role, fileId) => {
    if (!selectedProject) return;
    setBusyAction(`delete:${fileId}`);
    try {
      const res = await fetch(
        getApiUrl(`/api/longform/projects/${selectedProject.project_id}/files/${fileId}?role=${encodeURIComponent(role)}`),
        { method: 'DELETE' },
      );
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      await fetchProjects();
      setErrorMessage('');
    } catch (error) {
      setErrorMessage(error.message || 'Datei konnte nicht entfernt werden.');
    } finally {
      setBusyAction('');
    }
  };

  const handleReorder = async (role, orderedIds) => {
    if (!selectedProject) return;
    try {
      const res = await fetch(getApiUrl(`/api/longform/projects/${selectedProject.project_id}/files/reorder`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role, ordered_ids: orderedIds }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      await fetchProjects();
    } catch (error) {
      setErrorMessage(error.message || 'Reihenfolge konnte nicht gespeichert werden.');
    }
  };

  const handleMove = async (role, fileId, direction) => {
    const roleFiles = [...(selectedProject?.files?.[role] || [])];
    const index = roleFiles.findIndex((item) => item.id === fileId);
    if (index < 0) return;
    const swapIndex = direction === 'up' ? index - 1 : index + 1;
    if (swapIndex < 0 || swapIndex >= roleFiles.length) return;
    [roleFiles[index], roleFiles[swapIndex]] = [roleFiles[swapIndex], roleFiles[index]];
    await handleReorder(role, roleFiles.map((item) => item.id));
  };

  const handlePipelineAction = async (action) => {
    if (!selectedProject) return;
    if (action === 'restart') {
      const confirmed = window.confirm(
        'Pipeline wirklich neu starten?\n\nDabei werden erzeugte Zwischenartefakte, Analysen und Exporte dieses Projekts verworfen. Die Quelldateien bleiben erhalten.',
      );
      if (!confirmed) return;
    }
    setBusyAction(action);
    try {
      if (['start', 'resume', 'restart'].includes(action) && hasUnsavedProjectChanges) {
        await persistProjectDraft();
      }
      const runtimeBody = ['start', 'resume', 'restart'].includes(action)
        ? JSON.stringify({ ai: effectiveRuntimeAi })
        : null;
      const res = await fetch(getApiUrl(`/api/longform/projects/${selectedProject.project_id}/${action}`), {
        method: 'POST',
        headers: runtimeBody ? { 'Content-Type': 'application/json' } : undefined,
        body: runtimeBody,
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      await fetchProjects();
      setErrorMessage('');
    } catch (error) {
      setErrorMessage(error.message || `Aktion ${action} fehlgeschlagen.`);
    } finally {
      setBusyAction('');
    }
  };

  const handleLoadSpeakerStills = async () => {
    if (!selectedProject) return;
    setLoadingSpeakerStills(true);
    try {
      const res = await fetch(getApiUrl(`/api/longform/projects/${selectedProject.project_id}/speaker-stills?count=6`));
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      const stillsByRole = data.speaker_stills || {};
      const nextSelection = {};
      Object.entries(stillsByRole).forEach(([role, items]) => {
        if (items?.[0]?.path) {
          nextSelection[role] = items[0].path;
        }
      });
      setSelectedStillByRole(nextSelection);
      setDraftConfig((prev) => ({ ...prev, thumbnail_selected_stills: nextSelection }));
      await fetchProjects();
      setErrorMessage('');
    } catch (error) {
      setErrorMessage(error.message || 'Sprecher-Stills konnten nicht geladen werden.');
    } finally {
      setLoadingSpeakerStills(false);
    }
  };

  const handleThumbnailPresetChange = (presetId) => {
    const selectedPreset = availableThumbnailPromptPresets.find((item) => item.id === presetId);
    setDraftConfig((prev) => ({
      ...prev,
      thumbnail_prompt_preset_id: presetId,
      thumbnail_prompt_text: selectedPreset?.prompt || prev.thumbnail_prompt_text || '',
    }));
  };

  const handleGenerateTextOverlaySuggestions = async () => {
    if (!selectedProject) return;
    const basePrompt = String(draftConfig.thumbnail_prompt_text || '').trim();
    if (!basePrompt) {
      setErrorMessage('Bitte zuerst einen Thumbnail-Prompt eintragen.');
      return;
    }
    setGeneratingOverlaySuggestions(true);
    setErrorMessage('');
    setInfoMessage('KI erzeugt 10 Text-Overlay-Vorschlaege...');
    try {
      if (hasUnsavedProjectChanges) {
        await persistProjectDraft();
      }
      const res = await fetch(getApiUrl(`/api/longform/projects/${selectedProject.project_id}/thumbnail-text-overlays`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: basePrompt,
          count: 10,
          ai: effectiveRuntimeAi,
        }),
      });
      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }
      const data = await res.json();
      const suggestions = normalizeTextOverlaySuggestions(data.overlays);
      const nextOverlayText = String(draftConfig.thumbnail_text_overlay_text || '').trim() || suggestions[0] || '';
      setDraftConfig((prev) => ({
        ...prev,
        thumbnail_text_overlay_suggestions: suggestions,
        thumbnail_text_overlay_text: nextOverlayText,
      }));
      await fetchProjectBundle(selectedProject.project_id);
      setInfoMessage(`${suggestions.length} Text-Overlay-Vorschlaege geladen.`);
      setErrorMessage('');
    } catch (error) {
      setErrorMessage(error.message || 'Text-Overlay-Vorschlaege konnten nicht generiert werden.');
      setInfoMessage('');
    } finally {
      setGeneratingOverlaySuggestions(false);
    }
  };

  const handleGenerateThumbnails = async ({ useFeedback = false } = {}) => {
    if (!selectedProject) return;
    const providers = Array.isArray(draftConfig.thumbnail_provider_selection) ? draftConfig.thumbnail_provider_selection : [];
    if (!providers.length) {
      setErrorMessage('Bitte mindestens einen Thumbnail-Provider auswaehlen.');
      return;
    }
    const missingProviderConfigs = providers
      .filter((provider) => !getThumbnailProviderRuntimeStatus(provider, effectiveRuntimeAi).available)
      .map((provider) => `${provider}: ${getThumbnailProviderRuntimeStatus(provider, effectiveRuntimeAi).label}`);
    if (missingProviderConfigs.length) {
      setErrorMessage(`Thumbnail-Generierung nicht moeglich. Bitte zuerst konfigurieren: ${missingProviderConfigs.join(' · ')}`);
      return;
    }
    const basePrompt = String(draftConfig.thumbnail_prompt_text || '').trim();
    if (!basePrompt) {
      setErrorMessage('Bitte einen Thumbnail-Prompt eintragen.');
      return;
    }
    const feedbackText = String(draftConfig.thumbnail_feedback_text || '').trim();
    if (useFeedback && !feedbackText) {
      setErrorMessage('Bitte erst Feedback zur letzten Thumbnail-Runde eintragen.');
      return;
    }
    const overlayText = String(draftConfig.thumbnail_text_overlay_text || '').trim();
    if (basePrompt.includes('<text_overlay>') && !overlayText) {
      setErrorMessage('Bitte erst ein Text-Overlay auswaehlen oder bearbeiten.');
      return;
    }
    const effectivePrompt = useFeedback && feedbackText
      ? `${injectTextOverlayIntoPrompt(basePrompt, overlayText)}

FEEDBACK ZUR LETZTEN THUMBNAIL-RUNDE:
${feedbackText}

Erzeuge eine neue Runde, die dieses Feedback sichtbar umsetzt. Verbessere Motivwahl, Lesbarkeit, Emotion und Klickstaerke, ohne die Sprecher-Referenzen zu verlieren.`
      : injectTextOverlayIntoPrompt(basePrompt, overlayText);

    setGeneratingThumbnails(true);
    setErrorMessage('');
    setInfoMessage(useFeedback && feedbackText ? 'Thumbnail-Feedback wird verarbeitet... Bitte warten.' : 'Thumbnail-Generierung laeuft... Bitte warten.');
    try {
      if (hasUnsavedProjectChanges) {
        await persistProjectDraft();
      }
      const res = await fetch(getApiUrl(`/api/longform/projects/${selectedProject.project_id}/thumbnails/generate`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: effectivePrompt,
          providers,
          count_per_provider: Number(draftConfig.thumbnail_variations || 3),
          selected_stills: selectedStillByRole,
          provider_models: normalizeThumbnailProviderModels(
            draftConfig.thumbnail_provider_models,
            resolvedThumbnailModelDefaults,
          ),
          reference_order: draftMode === 'interview'
            ? ((draftConfig.thumbnail_reference_role_order || 'host_guest') === 'guest_host'
              ? ['guest', 'host']
              : ['host', 'guest'])
            : ['single'],
          feedback: useFeedback ? feedbackText : '',
          ai: effectiveRuntimeAi,
        }),
      });
      if (!res.ok) {
        const errMsg = await readErrorMessage(res);
        setErrorMessage(`Thumbnail-Generierung fehlgeschlagen: ${errMsg}`);
        setInfoMessage('');
        return;
      }
      const data = await res.json();
      setProjectBundle({ project: data.project, state: data.state, logs: data.logs || [] });
      await fetchProjects();
      setErrorMessage('');
      setInfoMessage(
        useFeedback && feedbackText
          ? `Thumbnail-Feedback verarbeitet. ${data.results?.length || 0} Bilder erstellt.`
          : `Thumbnail-Generierung abgeschlossen! ${data.results?.length || 0} Bilder erstellt.`,
      );
      setTimeout(() => setInfoMessage(''), 5000);
    } catch (error) {
      setErrorMessage(`Thumbnail-Generierung fehlgeschlagen: ${error.message || 'Unbekannter Fehler'}`);
      setInfoMessage('');
    } finally {
      setGeneratingThumbnails(false);
    }
  };

  const handleDeleteProject = async (projectId) => {
    if (!projectId) return;
    const targetProject =
      projects.find((item) => item.project_id === projectId) ||
      (selectedProject?.project_id === projectId ? selectedProject : null);
    const targetStatus =
      targetProject?.status ||
      (selectedProject?.project_id === projectId ? selectedState?.status : null);

    if (['queued', 'processing'].includes(targetStatus)) {
      setErrorMessage('Laufende Longform-Projekte bitte erst pausieren oder stoppen, bevor du sie loeschst.');
      return;
    }

    const targetName = targetProject?.project_name || 'dieses Projekt';
    const confirmed = window.confirm(
      `Projekt "${targetName}" wirklich loeschen?\n\nAlle lokalen Longform-Artefakte, Logs und Exporte dieses Projekts werden entfernt.`,
    );
    if (!confirmed) return;

    setBusyAction(`delete-project:${projectId}`);
    try {
      const res = await fetch(getApiUrl(`/api/longform/projects/${projectId}`), { method: 'DELETE' });
      if (!res.ok) throw new Error(await readErrorMessage(res));

      const remainingProjects = projects.filter((item) => item.project_id !== projectId);
      setProjects(remainingProjects);
      setErrorMessage('');

      if (selectedProjectId === projectId) {
        const nextProjectId = remainingProjects[0]?.project_id || '';
        setProjectBundle(null);
        if (nextProjectId) {
          setSelectedProjectId(nextProjectId);
          await fetchProjectBundle(nextProjectId);
        } else {
          setSelectedProjectId('');
          localStorage.removeItem(STORAGE_KEY);
        }
      }

      await fetchProjects();
    } catch (error) {
      setErrorMessage(error.message || 'Projekt konnte nicht geloescht werden.');
    } finally {
      setBusyAction('');
    }
  };

  useEffect(() => {
    if (!selectedProject?.project_id) return undefined;
    if (!['queued', 'processing'].includes(selectedState?.status)) return undefined;
    const interval = window.setInterval(() => {
      fetchProjectBundle(selectedProject.project_id).catch(() => {});
      fetchProjects().catch(() => {});
    }, 2500);
    return () => window.clearInterval(interval);
  }, [selectedProject?.project_id, selectedState?.status]);

  const handleDrop = async (role, targetFileId) => {
    const sourceFileId = dragState.fileId;
    if (!selectedProject || !sourceFileId || dragState.role !== role || sourceFileId === targetFileId) return;
    const roleFiles = [...(selectedProject.files?.[role] || [])];
    const sourceIndex = roleFiles.findIndex((item) => item.id === sourceFileId);
    const targetIndex = roleFiles.findIndex((item) => item.id === targetFileId);
    if (sourceIndex < 0 || targetIndex < 0) return;
    const [moved] = roleFiles.splice(sourceIndex, 1);
    roleFiles.splice(targetIndex, 0, moved);
    setDragState({ role: '', fileId: '' });
    await handleReorder(role, roleFiles.map((item) => item.id));
  };

  const projectArtifacts = selectedProject?.artifacts || {};
  const speakerStillsByRole = projectArtifacts.speaker_stills || {};
  const generatedThumbnailArtifacts = projectArtifacts.thumbnail_generations || {};
  const selectedThumbnailProviders = Array.isArray(draftConfig.thumbnail_provider_selection) ? draftConfig.thumbnail_provider_selection : [];
  const thumbnailProviderStatuses = useMemo(() => ({
    gemini: getThumbnailProviderRuntimeStatus('gemini', effectiveRuntimeAi),
    openai: getThumbnailProviderRuntimeStatus('openai', effectiveRuntimeAi),
    midjourney: getThumbnailProviderRuntimeStatus('midjourney', effectiveRuntimeAi),
  }), [effectiveRuntimeAi]);
  const unavailableSelectedThumbnailProviders = selectedThumbnailProviders
    .filter((provider) => !thumbnailProviderStatuses[provider]?.available)
    .map((provider) => `${provider}: ${thumbnailProviderStatuses[provider]?.label || 'Konfiguration fehlt'}`);
  const currentStatusStyle = STATUS_STYLES[selectedState?.status] || STATUS_STYLES.idle;
  const totalProgressPercent = Math.max(0, Math.min(100, Math.round((selectedState?.progress || 0) * 100)));
  const stepProgressPercent = Math.max(0, Math.min(100, Math.round((selectedState?.step_progress || 0) * 100)));
  const stepDetail = selectedState?.step_detail || null;

  return (
    <div className="h-full overflow-y-auto touch-scroll p-5 md:p-8 animate-[fadeIn_0.3s_ease-out]">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white">Longform Video Editor</h1>
          <p className="mt-2 text-sm text-zinc-500 max-w-3xl">
            Lokaler Rough-Cut für Podcast-Longforms mit Ingest, Sync, Whisper, konservativer Decision Engine,
            Review-Markern und Resolve-kompatiblem FCPXML-Export.
          </p>
        </div>
        <button
          type="button"
          onClick={refreshAll}
          disabled={loadingProjects || loadingBundle}
          className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-zinc-200 hover:bg-white/10 disabled:opacity-60"
        >
          {(loadingProjects || loadingBundle) ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
          Aktualisieren
        </button>
      </div>

      {errorMessage && (
        <div className="mb-6 flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          <AlertCircle size={18} />
          {errorMessage}
        </div>
      )}

      {infoMessage && (
        <div className="mb-6 flex items-center gap-3 rounded-2xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
          <CheckCircle2 size={18} />
          {infoMessage}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
        <div className="space-y-6">
          <div className="glass-panel p-5">
            <div className="flex items-center gap-2 mb-4 text-white font-semibold">
              <Plus size={18} /> Neues Projekt
            </div>
            <div className="space-y-3">
              <input
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                className="input-field"
                placeholder="Projektname"
              />
              <select value={createMode} onChange={(e) => setCreateMode(e.target.value)} className="input-field">
                <option value="single">Single Camera</option>
                <option value="interview">Interview</option>
              </select>
              <button
                type="button"
                onClick={handleCreateProject}
                disabled={busyAction === 'create'}
                className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-600 disabled:opacity-60"
              >
                {busyAction === 'create' ? <Loader2 size={16} className="animate-spin" /> : <Clapperboard size={16} />}
                Projekt erstellen
              </button>
            </div>
          </div>

          <div className="glass-panel p-5">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div className="text-white font-semibold">Projekte</div>
              <span className="text-xs text-zinc-500">{projects.length}</span>
            </div>
            <div className="space-y-3 max-h-[60vh] overflow-y-auto touch-scroll pr-1">
              {projects.map((project) => {
                const deleteBusy = busyAction === `delete-project:${project.project_id}`;
                const running = ['queued', 'processing'].includes(project.status);
                return (
                  <div
                    key={project.project_id}
                    className={`rounded-2xl border p-2 transition-colors ${
                      selectedProjectId === project.project_id
                        ? 'border-cyan-500/30 bg-cyan-500/10'
                        : 'border-white/10 bg-black/20 hover:bg-black/30'
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <button
                        type="button"
                        onClick={() => setSelectedProjectId(project.project_id)}
                        className="min-w-0 flex-1 rounded-xl px-2 py-2 text-left"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate font-medium text-white">{project.project_name}</div>
                            <div className="mt-1 text-xs text-zinc-500">
                              {project.mode === 'interview' ? 'Interview' : 'Single'} · {formatTimestamp(project.updated_at)}
                            </div>
                          </div>
                          <span className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-wide ${STATUS_STYLES[project.status] || STATUS_STYLES.idle}`}>
                            {project.status}
                          </span>
                        </div>
                        {project.message && (
                          <p className="mt-3 text-xs text-zinc-400 line-clamp-2">{project.message}</p>
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteProject(project.project_id)}
                        disabled={deleteBusy || running}
                        title={running ? 'Bitte das laufende Projekt zuerst pausieren oder stoppen.' : 'Projekt loeschen'}
                        className="rounded-xl border border-red-500/20 bg-red-500/10 p-2 text-red-200 hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {deleteBusy ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                      </button>
                    </div>
                  </div>
                );
              })}
              {!projects.length && !loadingProjects && (
                <div className="rounded-2xl border border-white/10 bg-black/20 px-4 py-5 text-sm text-zinc-500">
                  Noch keine Longform-Projekte vorhanden.
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          {!selectedProject && (
            <div className="glass-panel p-10 text-center text-zinc-500">
              Ein Projekt auswählen oder links neu anlegen.
            </div>
          )}

          {selectedProject && (
            <>
              <div className="glass-panel p-6">
                <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
                  <div>
                    <div className="flex items-center gap-3">
                      <h2 className="text-xl font-semibold text-white">{selectedProject.project_name}</h2>
                      <span className={`rounded-full border px-3 py-1 text-[11px] uppercase tracking-wide ${currentStatusStyle}`}>
                        {selectedState?.status || 'idle'}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-zinc-500">
                      Erstellt {formatTimestamp(selectedProject.created_at)} · letzter Status: {selectedState?.message || 'Bereit'}
                    </p>
                    <div className="mt-4 max-w-3xl space-y-3">
                      <div>
                        <div className="mb-1 flex items-center justify-between gap-3 text-xs text-zinc-400">
                          <span>Gesamtfortschritt</span>
                          <span>{totalProgressPercent}% · ETA {formatDuration(selectedState?.eta_seconds)}</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-white/10">
                          <div className="h-full rounded-full bg-cyan-400 transition-all duration-300" style={{ width: `${totalProgressPercent}%` }} />
                        </div>
                      </div>
                      {selectedState?.current_step && (
                        <div>
                          <div className="mb-1 flex items-center justify-between gap-3 text-xs text-zinc-400">
                            <span>Schritt {selectedState.current_step}</span>
                            <span>{stepProgressPercent}% · ETA {formatDuration(selectedState?.step_eta_seconds)}</span>
                          </div>
                          <div className="h-2 overflow-hidden rounded-full bg-white/10">
                            <div className="h-full rounded-full bg-emerald-400 transition-all duration-300" style={{ width: `${stepProgressPercent}%` }} />
                          </div>
                          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
                            <span>Gesamt gelaufen: {formatDuration(selectedState?.timings?.elapsed_seconds)}</span>
                            <span>Schritt gelaufen: {formatDuration(selectedState?.timings?.step_elapsed_seconds)}</span>
                            {stepDetail?.item_name && <span>Datei: {stepDetail.item_name}</span>}
                            {stepDetail?.item_role && <span>Rolle: {stepDetail.item_role}</span>}
                            {stepDetail?.item_stage && <span>Phase: {stepDetail.item_stage}</span>}
                            {stepDetail?.item_index && stepDetail?.item_count ? (
                              <span>Datei {stepDetail.item_index}/{stepDetail.item_count}</span>
                            ) : null}
                            {stepDetail?.decoded_audio_label && <span>Dekodiert: {stepDetail.decoded_audio_label}</span>}
                            {stepDetail?.decoded_segments ? <span>Segmente: {stepDetail.decoded_segments}</span> : null}
                            {stepDetail?.runtime_label ? <span>Runtime: {stepDetail.runtime_label}</span> : null}
                            {stepDetail?.retry_reason ? <span>Retry: {stepDetail.retry_reason}</span> : null}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => handlePipelineAction('start')}
                      disabled={busyAction === 'start' || ['queued', 'processing'].includes(selectedState?.status)}
                      className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-blue-600 disabled:opacity-60"
                    >
                      {busyAction === 'start' ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
                      Pipeline starten
                    </button>
                    <button
                      type="button"
                      onClick={() => handlePipelineAction('resume')}
                      disabled={busyAction === 'resume' || !selectedState?.can_resume}
                      className="inline-flex items-center gap-2 rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-4 py-2 text-sm font-semibold text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-60"
                    >
                      {busyAction === 'resume' ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
                      Fortsetzen
                    </button>
                    <button
                      type="button"
                      onClick={() => handlePipelineAction('restart')}
                      disabled={busyAction === 'restart' || ['queued', 'processing'].includes(selectedState?.status)}
                      className="inline-flex items-center gap-2 rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/10 px-4 py-2 text-sm font-semibold text-fuchsia-100 hover:bg-fuchsia-500/20 disabled:opacity-60"
                    >
                      {busyAction === 'restart' ? <Loader2 size={16} className="animate-spin" /> : <RotateCcw size={16} />}
                      Restart
                    </button>
                    <button
                      type="button"
                      onClick={() => handlePipelineAction('stop')}
                      disabled={busyAction === 'stop' || !['queued', 'processing'].includes(selectedState?.status)}
                      className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-500/20 disabled:opacity-60"
                    >
                      {busyAction === 'stop' ? <Loader2 size={16} className="animate-spin" /> : <PauseCircle size={16} />}
                      Stop / pausieren
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteProject(selectedProject.project_id)}
                      disabled={busyAction === `delete-project:${selectedProject.project_id}` || ['queued', 'processing'].includes(selectedState?.status)}
                      title={['queued', 'processing'].includes(selectedState?.status) ? 'Bitte das laufende Projekt zuerst pausieren oder stoppen.' : 'Projekt loeschen'}
                      className="inline-flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-2 text-sm font-semibold text-red-100 hover:bg-red-500/20 disabled:opacity-50"
                    >
                      {busyAction === `delete-project:${selectedProject.project_id}` ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                      Projekt loeschen
                    </button>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-5">
                  {Object.entries(selectedState?.steps || {}).map(([step, stepState]) => (
                    <div key={step} className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3">
                      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-zinc-500">
                        <span>{step}</span>
                        <HintBadge hint={STEP_HINTS[step] || ''} />
                      </div>
                      <div className="mt-2 flex items-center gap-2 text-sm text-white">
                        {stepState.status === 'completed' ? (
                          <CheckCircle2 size={16} className="text-emerald-300" />
                        ) : stepState.status === 'processing' ? (
                          <Loader2 size={16} className="animate-spin text-cyan-200" />
                        ) : (
                          <Clock3 size={16} className="text-zinc-500" />
                        )}
                        {stepState.status || 'pending'}
                      </div>
                      {stepState.message && (
                        <div className="mt-2 text-xs text-zinc-500 line-clamp-2">{stepState.message}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
                <div className="space-y-6">
                  <div className="glass-panel p-6">
                    <div className="flex items-center justify-between gap-4 mb-5">
                      <div>
                        <h3 className="text-lg font-semibold text-white">Projekt-Setup</h3>
                        <p className="mt-1 text-xs text-zinc-500">
                          Konservative Defaults mit editierbaren Regeln, lokal und resume-fähig.
                        </p>
                        {hasUnsavedProjectChanges && (
                          <div className="mt-2 text-xs text-amber-300">
                            Ungespeicherte Aenderungen. `Pipeline starten`, `Fortsetzen` und `Restart` speichern jetzt automatisch.
                          </div>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={handleSaveProject}
                        disabled={busyAction === 'save'}
                        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white hover:bg-white/10 disabled:opacity-60"
                      >
                        {busyAction === 'save' ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                        Speichern
                      </button>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <FieldLabel label="Projektname" hint={FIELD_HINTS.project_name} />
                        <input value={draftProjectName} onChange={(e) => setDraftProjectName(e.target.value)} className="input-field" />
                      </div>
                      <div>
                        <FieldLabel label="Modus" hint={FIELD_HINTS.mode} />
                        <select
                          value={draftMode}
                          onChange={(e) => {
                            const nextMode = e.target.value;
                            setDraftMode(nextMode);
                            setDraftConfig((prev) => ({
                              ...prev,
                              primary_audio_camera: nextMode === 'interview' ? 'host' : 'single',
                            }));
                          }}
                          className="input-field"
                        >
                          <option value="single">Single Camera</option>
                          <option value="interview">Interview</option>
                        </select>
                      </div>
                      <div>
                        <FieldLabel label="Preset" hint={FIELD_HINTS.preset} />
                        <select
                          value={draftConfig.preset}
                          onChange={(e) => setDraftConfig((prev) => ({ ...prev, preset: e.target.value }))}
                          className="input-field"
                        >
                          <option value="conservative">Conservative</option>
                          <option value="balanced">Balanced</option>
                          <option value="aggressive">Aggressive</option>
                        </select>
                      </div>
                      <div>
                        <FieldLabel label="Hauptaudio" hint={FIELD_HINTS.primary_audio_camera} />
                        <select
                          value={draftConfig.primary_audio_camera}
                          onChange={(e) => setDraftConfig((prev) => ({ ...prev, primary_audio_camera: e.target.value }))}
                          className="input-field"
                        >
                          {roles.map((role) => (
                            <option key={role} value={role}>{ROLE_LABELS[role]}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <div className="mt-5 rounded-2xl border border-cyan-500/20 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-50">
                      <div className="font-medium">Empfohlener Standard</div>
                      <div className="mt-1 text-xs leading-relaxed text-cyan-100/90">
                        OpenShorts analysiert standardmaessig nur kompaktes Audio und exportiert das XML mit Referenzen auf die Originalvideos.
                        <br />
                        `Normalisierung (CFR)` nur einschalten, wenn problematische Quellen wie Handy-, Webcam- oder Screenrecording-Material Drift oder Sync-Probleme machen.
                      </div>
                    </div>

                    <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                      {TOGGLE_OPTIONS.map(([key, label, hint]) => (
                        <label key={key} className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-300">
                          <div className="flex items-center gap-2">
                            <div className="font-medium text-white">{label}</div>
                            <HintBadge hint={FIELD_HINTS[key]} />
                          </div>
                          <div className="mt-1 text-xs text-zinc-500">{hint}</div>
                          <input
                            type="checkbox"
                            checked={!!draftConfig[key]}
                            onChange={(e) => setDraftConfig((prev) => ({ ...prev, [key]: e.target.checked }))}
                            className="mt-3 h-4 w-4"
                          />
                        </label>
                      ))}
                    </div>

                    <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                      <div>
                        <FieldLabel label="Export-FPS" hint={FIELD_HINTS.export_fps} />
                        <input type="number" value={draftConfig.export_fps} onChange={(e) => setDraftConfig((prev) => ({ ...prev, export_fps: clampNumber(e.target.value, 24) }))} className="input-field" />
                      </div>
                      <div>
                        <FieldLabel label="Min Shot Length (s)" hint={FIELD_HINTS.min_shot_length_sec} />
                        <input type="number" step="0.1" value={draftConfig.min_shot_length_sec} onChange={(e) => setDraftConfig((prev) => ({ ...prev, min_shot_length_sec: clampNumber(e.target.value, 3) }))} className="input-field" />
                      </div>
                      <div>
                        <FieldLabel label="Switch Hold (ms)" hint={FIELD_HINTS.speaker_switch_hold_ms} />
                        <input type="number" value={draftConfig.speaker_switch_hold_ms} onChange={(e) => setDraftConfig((prev) => ({ ...prev, speaker_switch_hold_ms: clampNumber(e.target.value, 900) }))} className="input-field" />
                      </div>
                      <div>
                        <FieldLabel label="Long Pause (ms)" hint={FIELD_HINTS.long_pause_threshold_ms} />
                        <input type="number" value={draftConfig.long_pause_threshold_ms} onChange={(e) => setDraftConfig((prev) => ({ ...prev, long_pause_threshold_ms: clampNumber(e.target.value, 650) }))} className="input-field" />
                      </div>
                      <div>
                        <FieldLabel label="Pause Target (ms)" hint={FIELD_HINTS.pause_trim_target_ms} />
                        <input type="number" value={draftConfig.pause_trim_target_ms} onChange={(e) => setDraftConfig((prev) => ({ ...prev, pause_trim_target_ms: clampNumber(e.target.value, 260) }))} className="input-field" />
                      </div>
                      <div>
                        <FieldLabel label="Filler Cut Level" hint={FIELD_HINTS.filler_word_cut_level} />
                        <select value={draftConfig.filler_word_cut_level} onChange={(e) => setDraftConfig((prev) => ({ ...prev, filler_word_cut_level: clampNumber(e.target.value, 1) }))} className="input-field">
                          <option value={0}>Off</option>
                          <option value={1}>Normal</option>
                          <option value={2}>Aggressiver</option>
                        </select>
                      </div>
                      <div>
                        <FieldLabel label="Backchannel Max (ms)" hint={FIELD_HINTS.backchannel_max_duration_ms} />
                        <input type="number" value={draftConfig.backchannel_max_duration_ms} onChange={(e) => setDraftConfig((prev) => ({ ...prev, backchannel_max_duration_ms: clampNumber(e.target.value, 700) }))} className="input-field" />
                      </div>
                      <div>
                        <FieldLabel label="Backchannel Max Words" hint={FIELD_HINTS.backchannel_max_words} />
                        <input type="number" value={draftConfig.backchannel_max_words} onChange={(e) => setDraftConfig((prev) => ({ ...prev, backchannel_max_words: clampNumber(e.target.value, 3) }))} className="input-field" />
                      </div>
                      <div>
                        <FieldLabel label="Review Threshold" hint={FIELD_HINTS.review_threshold} />
                        <input type="number" step="0.01" value={draftConfig.review_threshold} onChange={(e) => setDraftConfig((prev) => ({ ...prev, review_threshold: clampNumber(e.target.value, 0.62) }))} className="input-field" />
                      </div>
                      <div>
                        <FieldLabel label="Retake-Modus" hint={FIELD_HINTS.retake_mode} />
                        <select value={draftConfig.retake_mode} onChange={(e) => setDraftConfig((prev) => ({ ...prev, retake_mode: e.target.value }))} className="input-field">
                          <option value="off">Off</option>
                          <option value="aggressive_cut">Aggressive Cut</option>
                          <option value="mark">Mark</option>
                          <option value="conservative_cut">Conservative Cut</option>
                        </select>
                      </div>
                      <div>
                        <FieldLabel label="Sprache" hint={FIELD_HINTS.analysis_language} />
                        <input value={draftConfig.analysis_language} onChange={(e) => setDraftConfig((prev) => ({ ...prev, analysis_language: e.target.value }))} className="input-field" />
                      </div>
                    </div>
                  </div>

                  <div className="glass-panel p-6">
                    <div className="flex items-center gap-2 mb-4 text-white font-semibold">
                      <Film size={18} /> Ingest & Kamera-Dateien
                    </div>
                    <div className="space-y-4">
                      {roles.map((role) => {
                        const roleFiles = selectedProject.files?.[role] || [];
                        return (
                          <div key={role} className="rounded-2xl border border-white/10 bg-black/20 p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                              <div>
                                <div className="font-semibold text-white">{ROLE_LABELS[role]}</div>
                                <div className="text-xs text-zinc-500">Mehrere Segmente möglich. Reihenfolge per Drag oder Pfeile anpassen.</div>
                                <div className="mt-1 text-[11px] text-zinc-600">
                                  Uploads landen nur temporaer im Projektbereich und werden nach dem Ingest automatisch freigegeben.
                                </div>
                              </div>
                              <div className="flex flex-wrap items-center gap-2">
                                <FileUploadButton role={role} busy={busyAction === `upload:${role}`} onUpload={handleUploadRoleFiles} />
                              </div>
                            </div>
                            <div className="mb-4 rounded-xl border border-cyan-500/15 bg-cyan-500/5 p-3">
                              <div className="text-xs font-semibold uppercase tracking-wide text-cyan-200">Ohne Upload duplizieren</div>
                              <p className="mt-1 text-[11px] leading-relaxed text-zinc-400">
                                Wenn deine Dateien bereits auf einer gemounteten externen Platte oder im freigegebenen Host-Ordner liegen,
                                kannst du sie hier direkt per Pfad referenzieren. Dann bleibt das Original dort liegen und wird nicht hochgeladen.
                              </p>
                              <textarea
                                value={mountedPathDrafts[role] || ''}
                                onChange={(event) => setMountedPathDrafts((prev) => ({ ...prev, [role]: event.target.value }))}
                                rows={3}
                                className="mt-3 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                                placeholder={"/mnt/longform-source/IMG_8472.MOV\n/mnt/longform-source/IMG_2858.MOV"}
                              />
                              <div className="mt-3 rounded-xl border border-white/10 bg-black/20 p-3">
                                <div className="text-[11px] font-semibold uppercase tracking-wide text-zinc-300">Datei im Mount suchen</div>
                                <div className="mt-2 flex flex-wrap gap-2">
                                  <input
                                    value={mountedSearchQueries[role] || ''}
                                    onChange={(event) => setMountedSearchQueries((prev) => ({ ...prev, [role]: event.target.value }))}
                                    onKeyDown={(event) => {
                                      if (event.key === 'Enter') {
                                        event.preventDefault();
                                        handleSearchMountedFiles(role);
                                      }
                                    }}
                                    className="input-field flex-1 min-w-[220px]"
                                    placeholder="z. B. IMG_8472.MOV oder Teil des Namens"
                                  />
                                  <button
                                    type="button"
                                    onClick={() => handleSearchMountedFiles(role)}
                                    disabled={mountedSearchBusy[role]}
                                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white hover:bg-white/10 disabled:opacity-60"
                                  >
                                    {mountedSearchBusy[role] ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
                                    Im Mount suchen
                                  </button>
                                </div>
                                <div className="mt-2 text-[11px] text-zinc-500">
                                  Ein eindeutiger Dateiname reicht beim Import ebenfalls. Wenn mehrere Treffer existieren, waehle unten den richtigen aus.
                                </div>
                                {mountedSearchFeedback[role]?.message && (
                                  <div className={`mt-3 rounded-xl border px-3 py-2 text-xs ${
                                    mountedSearchFeedback[role]?.type === 'success'
                                      ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100'
                                      : 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                                  }`}>
                                    {mountedSearchFeedback[role].message}
                                  </div>
                                )}
                                {!!mountedSearchResults[role]?.length && (
                                  <div className="mt-3 max-h-56 space-y-2 overflow-y-auto touch-scroll pr-1">
                                    {mountedSearchResults[role].map((item) => (
                                      <button
                                        key={item.path}
                                        type="button"
                                        onClick={() => appendMountedPath(role, item.path)}
                                        className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-3 text-left hover:bg-white/10"
                                      >
                                        <div className="flex items-center justify-between gap-3">
                                          <div className="min-w-0">
                                            <div className="truncate text-sm font-medium text-white">{item.name}</div>
                                            <div className="mt-1 truncate text-[11px] text-zinc-400">{item.path}</div>
                                          </div>
                                          <div className="shrink-0 text-[11px] text-zinc-500">{formatBytes(item.size_bytes)}</div>
                                        </div>
                                      </button>
                                    ))}
                                  </div>
                                )}
                              </div>
                              <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
                                <div className="text-[11px] text-zinc-500">
                                  Nutze hier am sichersten Container-Pfade wie `/mnt/longform-source/...` oder `/app/output/longform_source_mount/...`. Mehrere Dateien: eine pro Zeile.
                                  Wenn die Suche trotz korrekt gemounteter Host-Platte leer bleibt, braucht Docker nach einer geaenderten Mount-Propagation einmal ein `docker compose up -d --force-recreate backend`.
                                </div>
                                <button
                                  type="button"
                                  onClick={() => handleImportMountedPaths(role)}
                                  disabled={busyAction === `import:${role}`}
                                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-60"
                                >
                                  {busyAction === `import:${role}` ? <Loader2 size={15} className="animate-spin" /> : <Film size={15} />}
                                  Per Pfad hinzufügen
                                </button>
                              </div>
                            </div>
                            <div className="space-y-2">
                              {roleFiles.map((file, index) => (
                                <div
                                  key={file.id}
                                  draggable
                                  onDragStart={() => setDragState({ role, fileId: file.id })}
                                  onDragOver={(event) => event.preventDefault()}
                                  onDrop={() => handleDrop(role, file.id)}
                                  className="flex flex-wrap items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-3 py-3"
                                >
                                  <div className="flex items-center gap-2 text-zinc-400">
                                    <GripVertical size={16} />
                                    <span className="text-xs">{index + 1}</span>
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <div className="truncate text-sm font-medium text-white">{file.original_name}</div>
                                    <div className="mt-1 text-xs text-zinc-500">
                                      {Math.round((file.duration_sec || 0) * 10) / 10}s · {file.width || '?'}x{file.height || '?'} · Sync {file.sync_confidence ?? '—'}
                                    </div>
                                    {file.source_deleted_at && (
                                      <div className="mt-1 text-[11px] text-cyan-300">
                                        Original-Upload bereits freigegeben, Arbeitsdateien bleiben im Projekt.
                                      </div>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <button type="button" onClick={() => handleMove(role, file.id, 'up')} className="rounded-lg border border-white/10 bg-black/20 p-2 text-zinc-300 hover:bg-black/30"><ArrowUp size={14} /></button>
                                    <button type="button" onClick={() => handleMove(role, file.id, 'down')} className="rounded-lg border border-white/10 bg-black/20 p-2 text-zinc-300 hover:bg-black/30"><ArrowDown size={14} /></button>
                                    <button type="button" onClick={() => handleDeleteFile(role, file.id)} disabled={busyAction === `delete:${file.id}`} className="rounded-lg border border-red-500/20 bg-red-500/10 p-2 text-red-200 hover:bg-red-500/20 disabled:opacity-60">
                                      {busyAction === `delete:${file.id}` ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                                    </button>
                                  </div>
                                </div>
                              ))}
                              {!roleFiles.length && (
                                <div className="rounded-xl border border-dashed border-white/10 bg-black/10 px-4 py-5 text-sm text-zinc-500">
                                  Noch keine Dateien für {ROLE_LABELS[role]} hochgeladen.
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>

                <div className="space-y-6">
                  <div className="glass-panel p-6">
                    <div className="flex items-center justify-between gap-3 mb-4">
                      <div className="flex items-center gap-2 text-white font-semibold">
                        <Clapperboard size={18} /> KI & Klassifikation
                      </div>
                      <button
                        type="button"
                        onClick={handleSaveAiDefaults}
                        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white hover:bg-white/10"
                      >
                        <Save size={15} />
                        Als Standard festlegen
                      </button>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <label className="block text-sm text-zinc-400 mb-2">Provider</label>
                        <select value={draftAi.provider} onChange={(e) => setDraftAi((prev) => ({ ...prev, provider: e.target.value }))} className="input-field">
                          <option value="off">Off</option>
                          <option value="ollama">Ollama</option>
                          <option value="gemini">Gemini</option>
                          <option value="openai">OpenAI</option>
                          <option value="claude">Claude</option>
                          <option value="minimax">Minimax</option>
                        </select>
                      </div>
                      {draftAi.provider === 'ollama' && (
                        <>
                          <div>
                            <label className="block text-sm text-zinc-400 mb-2">Ollama Model</label>
                            <input value={draftAi.ollama_model} onChange={(e) => setDraftAi((prev) => ({ ...prev, ollama_model: e.target.value }))} className="input-field" />
                          </div>
                          <div className="md:col-span-2">
                            <label className="block text-sm text-zinc-400 mb-2">Ollama Base URL</label>
                            <input value={draftAi.ollama_base_url} onChange={(e) => setDraftAi((prev) => ({ ...prev, ollama_base_url: e.target.value }))} className="input-field" />
                          </div>
                        </>
                      )}
                      <div className="md:col-span-2 rounded-2xl border border-white/10 bg-black/20 p-4 text-sm text-zinc-300">
                        <div className="font-medium text-white">API-Keys werden global verwaltet</div>
                        <p className="mt-2 text-xs leading-relaxed text-zinc-500">
                          Gemini-, Hugging-Face-/pyannote-, OpenAI-, Claude-, Minimax- und Midjourney-Zugaenge kommen jetzt ausschliesslich aus den App-Einstellungen.
                          Dieser Bereich steuert nur noch den Job-spezifischen Provider und optionale Ollama-Overrides.
                        </p>
                      </div>
                    </div>
                    <p className="mt-4 text-xs text-zinc-500">
                      Beim Start, Resume und Restart werden die globalen Runtime-Keys automatisch mitgegeben. So bleibt die Verwaltung zentral, ohne dass Longform-Jobs ihre eigenen Token-Felder brauchen.
                    </p>
                  </div>

                  <div className="glass-panel p-6">
                    <div className="flex items-center gap-2 mb-4 text-white font-semibold">
                      <CheckCircle2 size={18} /> Exporte & Summary
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                        <div className="text-xs uppercase tracking-wide text-zinc-500">Shots</div>
                        <div className="mt-2 text-2xl font-semibold text-white">{selectedState?.summary?.shot_count ?? 0}</div>
                      </div>
                      <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                        <div className="text-xs uppercase tracking-wide text-zinc-500">Review Marker</div>
                        <div className="mt-2 text-2xl font-semibold text-white">{selectedState?.summary?.review_marker_count ?? 0}</div>
                      </div>
                      <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                        <div className="text-xs uppercase tracking-wide text-zinc-500">Reaction Marker</div>
                        <div className="mt-2 text-2xl font-semibold text-white">{selectedState?.summary?.reaction_marker_count ?? 0}</div>
                      </div>
                      <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                        <div className="text-xs uppercase tracking-wide text-zinc-500">Cuts</div>
                        <div className="mt-2 text-2xl font-semibold text-white">{selectedState?.summary?.cut_count ?? 0}</div>
                      </div>
                    </div>

                    <div className="mt-5 space-y-3">
                      {Object.entries(projectArtifacts).map(([key, artifact]) => (
                        <a
                          key={key}
                          href={artifact?.url || '#'}
                          target="_blank"
                          rel="noreferrer"
                          className={`flex items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm transition-colors ${
                            artifact?.url ? 'hover:bg-white/10 text-white' : 'text-zinc-500 pointer-events-none'
                          }`}
                        >
                          <div>
                            <div className="font-medium">{artifact?.name || key}</div>
                            <div className="mt-1 text-xs text-zinc-500">{key}</div>
                          </div>
                          <Download size={16} />
                        </a>
                      ))}
                      {!Object.keys(projectArtifacts).length && (
                        <div className="rounded-2xl border border-dashed border-white/10 bg-black/10 px-4 py-5 text-sm text-zinc-500">
                          Nach erfolgreichem Export erscheinen hier FCPXML, decisions.json, markers.csv und Sync-Artefakte.
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="glass-panel p-6">
                    <div className="flex items-center justify-between gap-3 mb-4">
                      <div className="flex items-center gap-2 text-white font-semibold">
                        <Image size={18} /> Thumbnails & Sprecher-Stills
                      </div>
                      <button
                        type="button"
                        onClick={handleLoadSpeakerStills}
                        disabled={loadingSpeakerStills || selectedState?.status === 'processing'}
                        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white hover:bg-white/10 disabled:opacity-60"
                      >
                        {loadingSpeakerStills ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
                        6 Stills pro Sprecher laden
                      </button>
                    </div>

                    <div className="space-y-4">
                      <div className="grid gap-4 md:grid-cols-3">
                        <div>
                          <FieldLabel label="Prompt-Preset" hint="Globale Presets aus den Einstellungen. Beim Wechsel wird der Prompt in das Freitextfeld geladen und kann dort weiter angepasst werden." />
                          <select
                            value={draftConfig.thumbnail_prompt_preset_id || ''}
                            onChange={(e) => handleThumbnailPresetChange(e.target.value)}
                            className="input-field"
                          >
                            <option value="">Kein Preset</option>
                            {availableThumbnailPromptPresets.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <FieldLabel label="Versionen pro Provider" hint="Wie viele Varianten jede ausgewaehlte KI erzeugen soll." />
                          <input
                            type="number"
                            min={1}
                            max={6}
                            value={draftConfig.thumbnail_variations || 3}
                            onChange={(e) => setDraftConfig((prev) => ({ ...prev, thumbnail_variations: clampNumber(e.target.value, 3) }))}
                            className="input-field"
                          />
                        </div>
                        <div>
                          <FieldLabel label="Provider" hint="Mehrfachauswahl moeglich. Jeder Provider erzeugt die eingestellte Anzahl an Versionen." />
                          <div className="space-y-2 rounded-xl border border-white/10 bg-black/20 p-3">
                            {['gemini', 'openai', 'midjourney'].map((provider) => {
                              const activeProviders = Array.isArray(draftConfig.thumbnail_provider_selection) ? draftConfig.thumbnail_provider_selection : [];
                              const isChecked = activeProviders.includes(provider);
                              const providerStatus = thumbnailProviderStatuses[provider] || { available: false, label: 'Konfiguration fehlt' };
                              return (
                                <label key={provider} className="flex items-center justify-between gap-3 text-sm text-zinc-300">
                                  <span className="min-w-0">
                                    <span className="block capitalize">{provider === 'midjourney' ? 'Midjourney' : provider}</span>
                                    <span className={`block text-[11px] ${providerStatus.available ? 'text-emerald-400' : 'text-amber-400'}`}>{providerStatus.label}</span>
                                  </span>
                                  <input
                                    type="checkbox"
                                    checked={isChecked}
                                    onChange={(e) => setDraftConfig((prev) => {
                                      const currentProviders = Array.isArray(prev.thumbnail_provider_selection) ? prev.thumbnail_provider_selection : [];
                                      const nextProviders = e.target.checked
                                        ? [...new Set([...currentProviders, provider])]
                                        : currentProviders.filter((item) => item !== provider);
                                      return { ...prev, thumbnail_provider_selection: nextProviders };
                                    })}
                                  />
                                </label>
                              );
                            })}
                          </div>
                          {!!unavailableSelectedThumbnailProviders.length && (
                            <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                              Fuer die aktuelle Auswahl fehlt noch Konfiguration: {unavailableSelectedThumbnailProviders.join(' · ')}
                            </div>
                          )}
                        </div>
                      </div>

                      {draftMode === 'interview' && (
                        <div className="grid gap-4 md:grid-cols-3">
                          <div>
                            <FieldLabel label="Referenz-Reihenfolge" hint="Bestimmt, in welcher Reihenfolge Host- und Gast-Referenzen an die Bild-KI uebergeben werden. Hilft gegen vertauschte Sitzplaetze." />
                            <select
                              value={draftConfig.thumbnail_reference_role_order || 'host_guest'}
                              onChange={(e) => setDraftConfig((prev) => ({ ...prev, thumbnail_reference_role_order: e.target.value }))}
                              className="input-field"
                            >
                              <option value="host_guest">Host zuerst, dann Gast</option>
                              <option value="guest_host">Gast zuerst, dann Host</option>
                            </select>
                          </div>
                        </div>
                      )}

                      <div className="grid gap-4 md:grid-cols-3">
                        {(Array.isArray(draftConfig.thumbnail_provider_selection) ? draftConfig.thumbnail_provider_selection : []).map((provider) => {
                          const providerModels = normalizeThumbnailProviderModels(
                            draftConfig.thumbnail_provider_models,
                            resolvedThumbnailModelDefaults,
                          );
                          const suggestions = THUMBNAIL_MODEL_SUGGESTIONS[provider] || [];
                          return (
                            <div key={provider} className="rounded-2xl border border-white/10 bg-black/20 p-4">
                              <FieldLabel
                                label={`${provider === 'midjourney' ? 'Midjourney' : provider.charAt(0).toUpperCase() + provider.slice(1)}-Modell`}
                                hint={
                                  provider === 'midjourney'
                                    ? 'Freitext fuer deinen Midjourney-Bridge-Provider. Die Vorschlaege sind gaengige Aliase; was konkret funktioniert, bestimmt deine Bridge.'
                                    : 'Direktes Modell fuer diesen Bildprovider. Vorschlaege koennen uebernommen und danach frei angepasst werden.'
                                }
                              />
                              <input
                                type="text"
                                value={providerModels[provider] || ''}
                                onChange={(e) => setDraftConfig((prev) => ({
                                  ...prev,
                                  thumbnail_provider_models: {
                                    ...normalizeThumbnailProviderModels(prev.thumbnail_provider_models, resolvedThumbnailModelDefaults),
                                    [provider]: e.target.value,
                                  },
                                }))}
                                placeholder="Eigenes Modell eingeben"
                                className="input-field w-full font-mono"
                              />
                              <div className="mt-3 flex flex-wrap gap-2">
                                {suggestions.map((modelName) => (
                                  <button
                                    key={modelName}
                                    type="button"
                                    onClick={() => setDraftConfig((prev) => ({
                                      ...prev,
                                      thumbnail_provider_models: {
                                        ...normalizeThumbnailProviderModels(prev.thumbnail_provider_models, resolvedThumbnailModelDefaults),
                                        [provider]: modelName,
                                      },
                                    }))}
                                    className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                                      (providerModels[provider] || '') === modelName
                                        ? 'border-primary/50 bg-primary/20 text-white'
                                        : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'
                                    }`}
                                  >
                                    {modelName}
                                  </button>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <FieldLabel label="Text-Overlay" hint="Die KI erzeugt 10 kurze Thumbnail-Textideen. Du waehlt eine aus oder bearbeitest sie frei. Beim Generieren ersetzt dieser Text den Platzhalter <text_overlay> im Prompt." />
                            <p className="text-xs text-zinc-500">
                              Vorschlaege sind editierbar. Wenn dein Prompt keinen Platzhalter <code>&lt;text_overlay&gt;</code> enthaelt, bleibt er unveraendert.
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={handleGenerateTextOverlaySuggestions}
                            disabled={generatingOverlaySuggestions || generatingThumbnails}
                            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white hover:bg-white/10 disabled:opacity-60"
                          >
                            {generatingOverlaySuggestions ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                            10 KI-Vorschlaege
                          </button>
                        </div>

                        <div className="mt-4 grid gap-4 md:grid-cols-[260px_minmax(0,1fr)]">
                          <div>
                            <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Vorschlag waehlen</label>
                            <select
                              value={draftConfig.thumbnail_text_overlay_suggestions?.includes(draftConfig.thumbnail_text_overlay_text) ? draftConfig.thumbnail_text_overlay_text : ''}
                              onChange={(e) => setDraftConfig((prev) => ({ ...prev, thumbnail_text_overlay_text: e.target.value }))}
                              className="input-field"
                            >
                              <option value="">Kein gespeicherter Vorschlag</option>
                              {normalizeTextOverlaySuggestions(draftConfig.thumbnail_text_overlay_suggestions).map((item, index) => (
                                <option key={`${item}-${index}`} value={item}>{item}</option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Ausgewaehlter Text</label>
                            <input
                              type="text"
                              value={draftConfig.thumbnail_text_overlay_text || ''}
                              onChange={(e) => setDraftConfig((prev) => ({ ...prev, thumbnail_text_overlay_text: e.target.value }))}
                              className="input-field w-full"
                              placeholder="z. B. NACH 20 JAHREN RAUS"
                            />
                          </div>
                        </div>
                      </div>

                      <div>
                        <FieldLabel label="Thumbnail-Prompt" hint="Der finale Prompt fuer die Bildgenerierung. Die ausgewaehlten Sprecher-Stills werden als visuelle Referenzen mitgegeben." />
                        <textarea
                          value={draftConfig.thumbnail_prompt_text || ''}
                          onChange={(e) => setDraftConfig((prev) => ({ ...prev, thumbnail_prompt_text: e.target.value }))}
                          rows={5}
                          className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-primary/50"
                          placeholder="Beschreibe hier Stil, Komposition, Textmenge und Stimmung fuer die Thumbnail-Generierung..."
                        />
                      </div>

                      <div>
                        <FieldLabel label="Feedback auf letzte Runde" hint="Nach der ersten Generierung kannst du hier gezielt nachschaerfen, was besser werden soll: Gesichtsausdruck, Textgroesse, Komposition, Farben, Emotion oder Klickstaerke." />
                        <textarea
                          value={draftConfig.thumbnail_feedback_text || ''}
                          onChange={(e) => setDraftConfig((prev) => ({ ...prev, thumbnail_feedback_text: e.target.value }))}
                          rows={3}
                          className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-primary/50"
                          placeholder="Beispiel: Gast staerker in den Fokus, weniger Text, mehr Kontrast, expression heftiger, cleaner Hintergrund..."
                        />
                      </div>

                      <div className="space-y-4">
                        {roles.map((role) => {
                          const roleStills = speakerStillsByRole[role] || [];
                          return (
                            <div key={role} className="rounded-2xl border border-white/10 bg-black/20 p-4">
                              <div className="mb-3 flex items-center justify-between gap-3">
                                <div>
                                  <div className="font-medium text-white">{ROLE_LABELS[role]}-Stills</div>
                                  <div className="text-xs text-zinc-500">Waehle pro Sprecher ein Referenzbild fuer die KI-Generierung.</div>
                                </div>
                                <div className="flex items-center gap-2">
                                  {roleStills.length > 1 && (
                                    <button
                                      type="button"
                                      onClick={() => {
                                        // Random shuffle selection
                                        const randomIndex = Math.floor(Math.random() * roleStills.length);
                                        const nextSelection = { ...selectedStillByRole, [role]: roleStills[randomIndex].path };
                                        setSelectedStillByRole(nextSelection);
                                        setDraftConfig((prev) => ({ ...prev, thumbnail_selected_stills: nextSelection }));
                                      }}
                                      className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-white/10"
                                    >
                                      <Shuffle size={12} />
                                      Zufall
                                    </button>
                                  )}
                                  <div className="text-xs text-zinc-500">{roleStills.length} Treffer</div>
                                </div>
                              </div>
                              {roleStills.length ? (
                                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                                  {roleStills.map((item, index) => {
                                    const isSelected = selectedStillByRole[role] === item.path;
                                    return (
                                      <div key={`${role}-${item.path}-${index}`} className="relative">
                                        <button
                                          type="button"
                                          onClick={() => {
                                            const nextSelection = { ...selectedStillByRole, [role]: item.path };
                                            setSelectedStillByRole(nextSelection);
                                            setDraftConfig((prev) => ({ ...prev, thumbnail_selected_stills: nextSelection }));
                                          }}
                                          onMouseEnter={() => setHoveredStill(item)}
                                          onMouseLeave={() => setHoveredStill(null)}
                                          className={`w-full overflow-hidden rounded-2xl border text-left transition-all ${isSelected ? 'border-primary ring-2 ring-primary/40' : 'border-white/10 hover:border-white/20'}`}
                                        >
                                          <img src={item.url} alt={`${ROLE_LABELS[role]} Still ${index + 1}`} className="aspect-video w-full object-cover" />
                                          <div className="p-3">
                                            <div className="truncate text-sm font-medium text-white">{item.file_name || `${ROLE_LABELS[role]} ${index + 1}`}</div>
                                            <div className="mt-1 text-[11px] text-zinc-500">
                                              {formatDuration(item.local_time)} · Confidence {item.confidence ?? '—'}
                                            </div>
                                          </div>
                                        </button>
                                      </div>
                                    );
                                  })}
                                </div>
                              ) : (
                                <div className="rounded-xl border border-dashed border-white/10 bg-black/10 px-4 py-5 text-sm text-zinc-500">
                                  Noch keine Sprecher-Stills geladen.
                                </div>
                              )}
                            </div>
                          );
                        })}

                        {/* Hover Preview Panel */}
                        {hoveredStill && (
                          <div className="rounded-2xl border border-white/10 bg-black/40 p-4 backdrop-blur-sm">
                            <div className="mb-2 text-sm font-medium text-white">Vorschau</div>
                            <img
                              src={hoveredStill.url}
                              alt="Hover preview"
                              className="w-full rounded-xl object-contain max-h-64"
                            />
                            <div className="mt-3 space-y-1 text-xs text-zinc-400">
                              <div className="truncate">{hoveredStill.file_name || 'Unbekannt'}</div>
                              <div>Zeitpunkt: {formatDuration(hoveredStill.local_time)}</div>
                              <div>Global: {formatDuration(hoveredStill.global_time)}</div>
                              {hoveredStill.confidence !== undefined && (
                                <div>Confidence: {typeof hoveredStill.confidence === 'number' ? hoveredStill.confidence.toFixed(2) : hoveredStill.confidence}</div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="flex flex-wrap justify-end gap-3">
                        {!!generatedThumbnailArtifacts?.results?.length && (
                          <button
                            type="button"
                            onClick={() => handleGenerateThumbnails({ useFeedback: true })}
                            disabled={generatingThumbnails || loadingSpeakerStills}
                            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white hover:bg-white/10 disabled:opacity-60"
                          >
                            {generatingThumbnails ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
                            Mit Feedback neu generieren
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => handleGenerateThumbnails()}
                          disabled={generatingThumbnails || loadingSpeakerStills}
                          className="inline-flex items-center gap-2 rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-4 py-2 text-sm text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-60"
                        >
                          {generatingThumbnails ? <Loader2 size={15} className="animate-spin" /> : <Clapperboard size={15} />}
                          Thumbnail-Varianten generieren
                        </button>
                      </div>

                      {!!generatedThumbnailArtifacts?.results?.length && (
                        <div className="space-y-3">
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                              <div className="text-sm font-medium text-white">Letzte Generierung</div>
                              {!!generatedThumbnailArtifacts?.feedback && (
                                <div className="mt-1 max-w-3xl text-xs text-zinc-400">Feedback angewendet: {generatedThumbnailArtifacts.feedback}</div>
                              )}
                            </div>
                            <div className="text-xs text-zinc-500">{generatedThumbnailArtifacts.results.length} Dateien</div>
                          </div>
                          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                            {generatedThumbnailArtifacts.results.map((item, index) => (
                              <div
                                key={`${item.provider}-${item.url}-${index}`}
                                className="overflow-hidden rounded-2xl border border-white/10 bg-black/20"
                              >
                                <a href={item.url} target="_blank" rel="noreferrer" className="block">
                                  <img src={item.url} alt={item.name || `Thumbnail ${index + 1}`} className="aspect-video w-full object-cover" />
                                </a>
                                <div className="flex items-center justify-between gap-3 p-3">
                                  <div>
                                    <div className="text-sm font-medium text-white">{item.name || `Variante ${index + 1}`}</div>
                                    <div className="text-[11px] text-zinc-500 uppercase tracking-wide">{item.provider}</div>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <a
                                      href={item.url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-zinc-200 hover:bg-white/10"
                                    >
                                      Oeffnen
                                    </a>
                                    <a
                                      href={item.url}
                                      download={item.name || `thumbnail-${index + 1}.png`}
                                      className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-2.5 py-1.5 text-xs text-cyan-100 hover:bg-cyan-500/20"
                                    >
                                      <Download size={13} />
                                      Download
                                    </a>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {!!generatedThumbnailArtifacts?.errors?.length && (
                        <div className="rounded-2xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-200">
                          {generatedThumbnailArtifacts.errors.map((item, index) => (
                            <div key={`${item.provider}-${index}`}>{item.provider}: {item.error}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="glass-panel p-6">
                    <div className="flex items-center justify-between gap-3 mb-4">
                      <div className="text-white font-semibold">Logs</div>
                      <div className="text-xs text-zinc-500">Tail</div>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-black/30 p-4 max-h-[460px] overflow-y-auto touch-scroll font-mono text-[12px] leading-6 text-zinc-300 whitespace-pre-wrap break-words">
                      {selectedLogs.length ? selectedLogs.join('\n') : 'Noch keine Logs vorhanden.'}
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
