import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Download, Share2, Instagram, Youtube, Video, CheckCircle, AlertCircle, X, Loader2, Copy, Wand2, Type, Calendar, Clock, Languages, RotateCcw, Scissors, Sparkles, ChevronDown } from 'lucide-react';
import { getApiUrl } from '../config';
import SubtitleModal from './SubtitleModal';
import HookModal from './HookModal';
import TranslateModal from './TranslateModal';
import TrimModal from './TrimModal';
import { DEFAULT_SOCIAL_POST_SETTINGS, INSTAGRAM_SHARE_MODES, SOCIAL_PLATFORM_OPTIONS, TIKTOK_POST_MODES } from '../socialOptions';

const resolveVideoUrl = (value) => {
    if (!value) return '';
    return value.startsWith('http://') || value.startsWith('https://') ? value : getApiUrl(value);
};

const extractFilenameFromVideoUrl = (value) => {
    if (!value) return '';
    try {
        const parsed = new URL(value, window.location.origin);
        const pathname = parsed.pathname || '';
        const filename = pathname.split('/').pop() || '';
        return decodeURIComponent(filename);
    } catch (error) {
        const [withoutQuery] = String(value).split('?');
        return decodeURIComponent((withoutQuery.split('/').pop() || '').trim());
    }
};

const POST_STATUS_POLL_INTERVAL_MS = 4000;
const PLATFORM_LABELS = SOCIAL_PLATFORM_OPTIONS.reduce((acc, item) => {
    acc[item.key] = item.label;
    return acc;
}, {});

const getPlatformLabel = (platform) => PLATFORM_LABELS[platform] || platform;

const normalizePlatformKey = (value) => {
    const normalized = (value || '').toString().trim().toLowerCase();
    if (!normalized) return '';
    if (normalized === 'twitter') return 'x';
    if (normalized === 'yt') return 'youtube';
    if (normalized === 'ig') return 'instagram';
    if (normalized === 'fb') return 'facebook';
    return normalized;
};

const buildDisplayPlatformResults = (result) => {
    if (!result) return [];

    const requested = (result.requested_platforms || [])
        .map(normalizePlatformKey)
        .filter(Boolean);
    const resultRows = (result.platform_results || []).map((item) => ({
        ...item,
        platform: normalizePlatformKey(item.platform),
    })).filter((item) => item.platform);

    if (!requested.length && !resultRows.length) {
        return [];
    }

    const byPlatform = new Map();
    for (const item of resultRows) {
        byPlatform.set(item.platform, item);
    }

    const requestedSet = new Set(requested);
    const rows = [];
    for (const option of SOCIAL_PLATFORM_OPTIONS) {
        const key = option.key;
        if (byPlatform.has(key)) {
            rows.push(byPlatform.get(key));
            continue;
        }
        if (requestedSet.has(key)) {
            rows.push({
                platform: key,
                success: null,
                status: 'pending',
                message: 'Warte auf Rückmeldung von Upload-Post.',
            });
            continue;
        }
        rows.push({
            platform: key,
            success: null,
            status: 'not_selected',
            message: 'Nicht für diesen Post ausgewählt.',
        });
    }

    return rows;
};

const resolveClipPostHighlight = (clip) => {
    const status = clip?.social_post_status;
    if (!status) return null;

    const pendingCount = Number(status.pending_count || 0);
    const successCount = Number(status.success_count || 0);
    const failureCount = Number(status.failure_count || 0);
    const normalizedStatus = String(status.status || '').toLowerCase();

    if (normalizedStatus === 'scheduled' || pendingCount > 0) {
        return {
            label: 'Gequeued',
            badgeClass: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100',
            cardClass: 'border-cyan-500/25 bg-cyan-950/35 shadow-[0_0_0_1px_rgba(34,211,238,0.08)]',
            previewClass: 'bg-cyan-950/55 border-b border-cyan-500/20',
            contentClass: 'bg-cyan-950/35',
        };
    }
    if (successCount > 0 && failureCount === 0) {
        return {
            label: 'Gepostet',
            badgeClass: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100',
            cardClass: 'border-emerald-500/30 bg-emerald-950/55 shadow-[0_0_0_1px_rgba(16,185,129,0.10)]',
            previewClass: 'bg-emerald-950/75 border-b border-emerald-500/20',
            contentClass: 'bg-emerald-950/55',
        };
    }
    if (successCount > 0 && failureCount > 0) {
        return {
            label: 'Teilweise',
            badgeClass: 'border-amber-500/30 bg-amber-500/10 text-amber-100',
            cardClass: 'border-amber-500/25 bg-amber-950/35 shadow-[0_0_0_1px_rgba(245,158,11,0.08)]',
            previewClass: 'bg-amber-950/55 border-b border-amber-500/20',
            contentClass: 'bg-amber-950/30',
        };
    }
    if (failureCount > 0 || normalizedStatus === 'failed') {
        return {
            label: 'Fehlgeschlagen',
            badgeClass: 'border-red-500/30 bg-red-500/10 text-red-100',
            cardClass: 'border-red-500/25 bg-red-950/35 shadow-[0_0_0_1px_rgba(239,68,68,0.08)]',
            previewClass: 'bg-red-950/55 border-b border-red-500/20',
            contentClass: 'bg-red-950/30',
        };
    }
    return {
        label: 'Upload aktiv',
        badgeClass: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100',
        cardClass: 'border-cyan-500/25 bg-cyan-950/35 shadow-[0_0_0_1px_rgba(34,211,238,0.08)]',
        previewClass: 'bg-cyan-950/55 border-b border-cyan-500/20',
        contentClass: 'bg-cyan-950/35',
    };
};

export default function ResultCard({ clip, index, jobId, uploadPostKey, uploadUserId, geminiApiKey, llmProvider, ollamaBaseUrl, ollamaModel, elevenLabsKey, pexelsKey, subtitleStyle, hookStyle, tightEditPreset, socialPostSettings = DEFAULT_SOCIAL_POST_SETTINGS, jobInstagramCollaborators = '', activeUploadProfile, onApplySubtitleDefaultsToJob, onApplyHookDefaultsToJob, onApplyInstagramCollaboratorsToJob, currentVideoOverride, onVideoVariantChange, onClipUpdated, onPlay, onPause, hookDraftText, onHookDraftChange, isSelected = false, onToggleSelect }) {
    const [showModal, setShowModal] = useState(false);
    const [showSubtitleModal, setShowSubtitleModal] = useState(false);
    const videoRef = React.useRef(null);
    const originalVideoUrl = resolveVideoUrl(clip.original_video_url || clip.base_video_url || clip.video_url);
    const currentVideoUrl = resolveVideoUrl(currentVideoOverride || clip.video_url || clip.preview_video_url);
    const clipIndex = clip.clip_index ?? index;
    const clipVersions = clip.versions || [];
    const activeVersionId = clip.active_version_id || clipVersions[clipVersions.length - 1]?.id || '';
    const originalVersionId = clip.original_version_id || clipVersions[0]?.id || '';
    const isPreviewOnly = !clip.video_url && !!clip.preview_video_url;
    const previewStart = Math.max(0, Number(clip.preview_start ?? clip.start ?? 0));
    const previewEnd = Math.max(previewStart + 0.15, Number(clip.preview_end ?? clip.end ?? previewStart + 15));
    const resolvedHookDraftText = hookDraftText ?? clip.hook_settings?.text ?? clip.viral_hook_text ?? '';
    const resolvedClipTitle = clip.video_title_for_youtube_short || "Viraler Clip erzeugt";
    const resolvedClipDescription = clip.video_description_for_instagram || clip.video_description_for_tiktok || "";
    const resolvedClipInstagramCollaborators = String(clip.instagram_collaborators || '').trim();
    const resolvedJobInstagramCollaborators = String(jobInstagramCollaborators || '').trim();
    const clipPostHighlight = resolveClipPostHighlight(clip);

    const [platforms, setPlatforms] = useState({ ...DEFAULT_SOCIAL_POST_SETTINGS.platforms, ...(socialPostSettings.platforms || {}) });
    const [postTitle, setPostTitle] = useState("");
    const [postDescription, setPostDescription] = useState("");
    const [firstComment, setFirstComment] = useState("");
    const [isScheduling, setIsScheduling] = useState(false);
    const [scheduleDate, setScheduleDate] = useState("");
    const [instagramShareMode, setInstagramShareMode] = useState(socialPostSettings.instagramShareMode || 'CUSTOM');
    const [instagramCollaborators, setInstagramCollaborators] = useState('');
    const [tiktokPostMode, setTiktokPostMode] = useState(socialPostSettings.tiktokPostMode || 'DIRECT_POST');
    const [tiktokIsAigc, setTiktokIsAigc] = useState(!!socialPostSettings.tiktokIsAigc);
    const [facebookPageId, setFacebookPageId] = useState(socialPostSettings.facebookPageId || '');
    const [pinterestBoardId, setPinterestBoardId] = useState(socialPostSettings.pinterestBoardId || '');

    const [posting, setPosting] = useState(false);
    const [postResult, setPostResult] = useState(null);
    const [isRefreshingPostStatus, setIsRefreshingPostStatus] = useState(false);
    const [retryingPlatformAction, setRetryingPlatformAction] = useState('');
    const postStatusTimeoutRef = React.useRef(null);

    const [isEditing, setIsEditing] = useState(false);
    const [isSubtitling, setIsSubtitling] = useState(false);
    const [isHooking, setIsHooking] = useState(false);
    const [isTranslating, setIsTranslating] = useState(false);
    const [isTrimming, setIsTrimming] = useState(false);
    const [isPreviewRendering, setIsPreviewRendering] = useState(false);
    const [isRenderingClip, setIsRenderingClip] = useState(false);
    const [isSelectingVersion, setIsSelectingVersion] = useState(false);
    const [showHookModal, setShowHookModal] = useState(false);
    const [showTranslateModal, setShowTranslateModal] = useState(false);
    const [showTrimModal, setShowTrimModal] = useState(false);
    const [trimDialogVideoUrl, setTrimDialogVideoUrl] = useState('');
    const [editError, setEditError] = useState(null);
    const [showMoreOptions, setShowMoreOptions] = useState(false);
    const [applyStockOverlay, setApplyStockOverlay] = useState(false);
    const [titleDraft, setTitleDraft] = useState(resolvedClipTitle);
    const [descriptionDraft, setDescriptionDraft] = useState(resolvedClipDescription);
    const [instagramCollaboratorsDraft, setInstagramCollaboratorsDraft] = useState(resolvedClipInstagramCollaborators);
    const [isSavingTextMetadata, setIsSavingTextMetadata] = useState(false);
    const [isApplyingJobCollaborators, setIsApplyingJobCollaborators] = useState(false);
    const [textMetadataStatus, setTextMetadataStatus] = useState(null);
    const isBusy = isEditing || isSubtitling || isHooking || isTranslating || isTrimming || isPreviewRendering || isRenderingClip || isSelectingVersion;
    const clipDuration = Number.isFinite(Number(clip.display_duration))
        ? Number(clip.display_duration)
        : Math.max(0, (clip.end || 0) - (clip.start || 0));
    const displayPlatformResults = buildDisplayPlatformResults(postResult);
    const resolvedUploadUserId = activeUploadProfile || uploadUserId;

    useEffect(() => {
        setTitleDraft(resolvedClipTitle);
        setDescriptionDraft(resolvedClipDescription);
        setInstagramCollaboratorsDraft(resolvedClipInstagramCollaborators);
    }, [resolvedClipTitle, resolvedClipDescription, resolvedClipInstagramCollaborators]);

    // Initialize/Reset form when modal opens
    useEffect(() => {
        if (showModal) {
            const savedPostStatus = clip.social_post_status || null;
            setPostTitle(clip.video_title_for_youtube_short || "Viraler Short");
            setPostDescription(clip.video_description_for_instagram || clip.video_description_for_tiktok || "");
            setFirstComment("");
            setIsScheduling(false);
            setScheduleDate("");
            setPlatforms({ ...DEFAULT_SOCIAL_POST_SETTINGS.platforms, ...(socialPostSettings.platforms || {}) });
            setInstagramShareMode(socialPostSettings.instagramShareMode || 'CUSTOM');
            setInstagramCollaborators((resolvedClipInstagramCollaborators || resolvedJobInstagramCollaborators || '').trim());
            setTiktokPostMode(socialPostSettings.tiktokPostMode || 'DIRECT_POST');
            setTiktokIsAigc(!!socialPostSettings.tiktokIsAigc);
            setFacebookPageId(socialPostSettings.facebookPageId || '');
            setPinterestBoardId(socialPostSettings.pinterestBoardId || '');
            setPostResult(savedPostStatus);
            if (savedPostStatus && (savedPostStatus.request_id || savedPostStatus.job_id) && (
                savedPostStatus.pending_count > 0
                || savedPostStatus.status === 'pending'
                || savedPostStatus.status === 'in_progress'
                || savedPostStatus.status === 'scheduled'
            )) {
                refreshPostStatus(savedPostStatus, { silent: true });
            }
        }
    }, [showModal, clip, socialPostSettings, resolvedClipInstagramCollaborators, resolvedJobInstagramCollaborators]);

    useEffect(() => {
        if (videoRef.current) {
            videoRef.current.load();
        }
    }, [currentVideoUrl]);

    useEffect(() => () => {
        if (postStatusTimeoutRef.current) {
            clearTimeout(postStatusTimeoutRef.current);
        }
    }, []);

    useEffect(() => {
        if (!showModal && postStatusTimeoutRef.current) {
            clearTimeout(postStatusTimeoutRef.current);
            postStatusTimeoutRef.current = null;
        }
    }, [showModal]);

    const isModifiedVideo = activeVersionId ? activeVersionId !== originalVersionId : currentVideoUrl !== originalVideoUrl;

    const readErrorText = async (res) => {
        const errText = await res.text();
        try {
            const jsonErr = JSON.parse(errText);
            return jsonErr.detail || errText;
        } catch (e) {
            return errText;
        }
    };

    useEffect(() => {
        if (!textMetadataStatus || textMetadataStatus.type !== 'success') return undefined;
        const timer = window.setTimeout(() => setTextMetadataStatus(null), 2200);
        return () => window.clearTimeout(timer);
    }, [textMetadataStatus]);

    const persistClipTextMetadata = async () => {
        const normalizedTitle = String(titleDraft || '').trim();
        const normalizedDescription = String(descriptionDraft || '').trim();
        const normalizedCollaborators = String(instagramCollaboratorsDraft || '').trim();
        const currentTitle = String(clip.video_title_for_youtube_short || '').trim();
        const currentDescription = String(resolvedClipDescription || '').trim();
        const currentCollaborators = String(clip.instagram_collaborators || '').trim();

        if (
            normalizedTitle === currentTitle
            && normalizedDescription === currentDescription
            && normalizedCollaborators === currentCollaborators
        ) {
            return;
        }

        setIsSavingTextMetadata(true);
        setTextMetadataStatus({ type: 'saving', message: 'Speichert...' });

        try {
            const res = await fetch(getApiUrl('/api/clip/text-metadata'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    video_title_for_youtube_short: normalizedTitle,
                    video_description_for_tiktok: normalizedDescription,
                    video_description_for_instagram: normalizedDescription,
                    instagram_collaborators: normalizedCollaborators,
                })
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            if (data?.clip && onClipUpdated) {
                onClipUpdated(data.clip);
            }
            setTextMetadataStatus({ type: 'success', message: 'Gespeichert' });
        } catch (e) {
            setTextMetadataStatus({ type: 'error', message: e.message || 'Konnte nicht gespeichert werden.' });
        } finally {
            setIsSavingTextMetadata(false);
        }
    };

    const handleApplyCollaboratorsToJob = async () => {
        if (!onApplyInstagramCollaboratorsToJob) return;

        setIsApplyingJobCollaborators(true);
        try {
            await persistClipTextMetadata();
            await onApplyInstagramCollaboratorsToJob(instagramCollaboratorsDraft);
            setTextMetadataStatus({ type: 'success', message: 'Fuer den Job uebernommen' });
        } catch (e) {
            setTextMetadataStatus({ type: 'error', message: e.message || 'Konnte Job-Default nicht speichern.' });
        } finally {
            setIsApplyingJobCollaborators(false);
        }
    };

    const applyClipResponse = (data) => {
        if (data?.clip && onClipUpdated) {
            onClipUpdated(data.clip);
            onVideoVariantChange && onVideoVariantChange(null);
            return;
        }
        if (data?.new_video_url) {
            onVideoVariantChange && onVideoVariantChange(data.new_video_url);
        }
    };

    const shouldPollPostStatus = (data) => Boolean(
        data
        && (data.request_id || data.job_id)
        && (
            data.pending_count > 0
            || data.status === 'pending'
            || data.status === 'in_progress'
            || data.status === 'scheduled'
        )
    );

    const normalizeOllamaModelName = (value) => {
        const trimmed = (value || '').trim();
        const aliasMap = {
            'gemma-3-12b': 'gemma3:12b',
            'gemma-3-12b:latest': 'gemma3:12b',
            'gemma3-12b': 'gemma3:12b',
            'gemma3-12b:latest': 'gemma3:12b',
        };
        return aliasMap[trimmed.toLowerCase()] || trimmed;
    };

    const buildLlmHeaders = () => {
        const provider = (llmProvider || localStorage.getItem('llm_provider') || 'gemini').trim().toLowerCase();
        const apiKey = geminiApiKey || localStorage.getItem('gemini_key');
        const pexelsApiKey = pexelsKey;
        const resolvedOllamaBaseUrl = ollamaBaseUrl || localStorage.getItem('ollama_base_url') || 'http://127.0.0.1:11434';
        const resolvedOllamaModel = normalizeOllamaModelName(
            ollamaModel || localStorage.getItem('ollama_model') || 'llama3.1:8b'
        );

        const headers = {
            'Content-Type': 'application/json',
            'X-LLM-Provider': provider,
        };
        if (provider === 'gemini' && apiKey) {
            headers['X-Gemini-Key'] = apiKey;
        }
        if (provider === 'ollama') {
            if (resolvedOllamaBaseUrl) headers['X-Ollama-Base-Url'] = resolvedOllamaBaseUrl;
            if (resolvedOllamaModel) headers['X-Ollama-Model'] = resolvedOllamaModel;
        }
        if (pexelsApiKey) {
            headers['X-Pexels-Key'] = pexelsApiKey;
        }
        return headers;
    };

    const stopPostStatusPolling = () => {
        if (postStatusTimeoutRef.current) {
            clearTimeout(postStatusTimeoutRef.current);
            postStatusTimeoutRef.current = null;
        }
    };

    const refreshPostStatus = async (tracking = postResult, { silent = false } = {}) => {
        if (!tracking || (!tracking.request_id && !tracking.job_id) || !uploadPostKey) {
            return;
        }

        stopPostStatusPolling();

        if (!silent) {
            setIsRefreshingPostStatus(true);
        }

        try {
            const params = new URLSearchParams();
            if (tracking.request_id) params.set('request_id', tracking.request_id);
            if (tracking.job_id) params.set('vendor_job_id', tracking.job_id);
            const trackingPlatforms = tracking.tracking_platforms?.length
                ? tracking.tracking_platforms
                : tracking.requested_platforms;
            if (trackingPlatforms?.length) params.set('platforms', trackingPlatforms.join(','));
            if (tracking.scheduled) params.set('scheduled', 'true');
            params.set('job_id', jobId);
            params.set('clip_index', String(clipIndex));

            const res = await fetch(getApiUrl(`/api/social/post/status?${params.toString()}`), {
                headers: {
                    'X-Upload-Post-Key': uploadPostKey,
                },
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            setPostResult(data);
            applyClipResponse(data);

            if (showModal && shouldPollPostStatus(data)) {
                stopPostStatusPolling();
                postStatusTimeoutRef.current = window.setTimeout(() => {
                    refreshPostStatus(data, { silent: true });
                }, POST_STATUS_POLL_INTERVAL_MS);
            } else {
                stopPostStatusPolling();
            }
        } catch (e) {
            setPostResult((prev) => prev ? {
                ...prev,
                poll_error: e.message,
            } : {
                success: false,
                status: 'failed',
                message: e.message,
                platform_results: [],
            });
            stopPostStatusPolling();
        } finally {
            if (!silent) {
                setIsRefreshingPostStatus(false);
            }
        }
    };

    const handleAutoEdit = async () => {
        setIsEditing(true);
        setEditError(null);
        try {
            const provider = llmProvider || localStorage.getItem('llm_provider') || 'gemini';
            const apiKey = geminiApiKey || localStorage.getItem('gemini_key');
            const resolvedOllamaBaseUrl = ollamaBaseUrl || localStorage.getItem('ollama_base_url') || 'http://127.0.0.1:11434';
            const resolvedOllamaModel = normalizeOllamaModelName(
                ollamaModel || localStorage.getItem('ollama_model') || 'llama3.1:8b'
            );

            if (provider === 'gemini' && !apiKey) {
                throw new Error("Gemini API-Key fehlt. Bitte in den Einstellungen setzen.");
            }
            if (provider === 'ollama' && !resolvedOllamaModel) {
                throw new Error("Ollama-Modell fehlt. Bitte in den Einstellungen setzen.");
            }

            const res = await fetch(getApiUrl('/api/edit'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(provider === 'gemini' && apiKey ? { 'X-Gemini-Key': apiKey } : {})
                },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    input_filename: currentVideoUrl.split('/').pop(),
                    provider,
                    ...(provider === 'ollama' ? {
                        ollama_base_url: resolvedOllamaBaseUrl,
                        ollama_model: resolvedOllamaModel
                    } : {})
                })
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            applyClipResponse(data);

        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsEditing(false);
        }
    };

    const handleSubtitle = async (options) => {
        setIsSubtitling(true);
        setEditError(null);
        try {
            const res = await fetch(getApiUrl('/api/subtitle'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    position: options.position,
                    y_position: options.yPosition,
                    font_size: options.fontSize,
                    font_family: options.fontFamily,
                    background_style: options.backgroundStyle,
                    input_filename: currentVideoUrl.split('/').pop()
                })
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            applyClipResponse(data);
            setShowSubtitleModal(false);

        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsSubtitling(false);
        }
    };

    const handleHook = async (hookData) => {
        setIsHooking(true);
        setEditError(null);
        try {
            // Support both string (legacy) and object
            const payload = typeof hookData === 'string'
                ? { text: hookData, xPosition: 50, yPosition: 12, textAlign: 'center', size: 'M', widthPreset: 'wide' }
                : hookData;
            onHookDraftChange && onHookDraftChange(payload.text || '');

            const res = await fetch(getApiUrl('/api/hook'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    text: payload.text,
                    position: payload.position,
                    horizontal_position: payload.horizontalPosition,
                    x_position: payload.xPosition ?? 50,
                    y_position: payload.yPosition ?? 12,
                    text_align: payload.textAlign ?? payload.horizontalPosition ?? 'center',
                    size: payload.size,
                    width_preset: payload.widthPreset,
                    font_family: payload.fontFamily,
                    background_style: payload.backgroundStyle,
                    input_filename: currentVideoUrl.split('/').pop()
                })
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            applyClipResponse(data);
            setShowHookModal(false);

        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsHooking(false);
        }
    };

    const handleTranslate = async (options) => {
        console.log('[Translate] Starting translation with options:', options);
        setIsTranslating(true);
        setEditError(null);
        try {
            const apiKey = elevenLabsKey;
            console.log('[Translate] API Key available:', !!apiKey);

            if (!apiKey) {
                throw new Error("ElevenLabs API-Key fehlt. Bitte in den Einstellungen setzen.");
            }

            const requestBody = {
                job_id: jobId,
                clip_index: clipIndex,
                target_language: options.targetLanguage,
                input_filename: currentVideoUrl.split('/').pop()
            };
            console.log('[Translate] Request body:', requestBody);
            console.log('[Translate] Sending request to /api/translate');

            const res = await fetch(getApiUrl('/api/translate'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-ElevenLabs-Key': apiKey
                },
                body: JSON.stringify(requestBody)
            });

            console.log('[Translate] Response status:', res.status);

            if (!res.ok) {
                const errorMessage = await readErrorText(res);
                console.error('[Translate] Error response:', errorMessage);
                throw new Error(errorMessage);
            }

            const data = await res.json();
            console.log('[Translate] Success response:', data);
            applyClipResponse(data);
            setShowTranslateModal(false);

        } catch (e) {
            console.error('[Translate] Exception:', e);
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsTranslating(false);
        }
    };

    const handleVersionSelect = async (versionId) => {
        if (!versionId || versionId === activeVersionId) return;
        setIsSelectingVersion(true);
        setEditError(null);
        try {
            const res = await fetch(getApiUrl('/api/clip/version/select'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    version_id: versionId,
                })
            });
            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }
            const data = await res.json();
            applyClipResponse(data);
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsSelectingVersion(false);
        }
    };

    const restoreOriginalVersion = async () => {
        setEditError(null);
        setShowSubtitleModal(false);
        setShowHookModal(false);
        setShowTranslateModal(false);
        setShowTrimModal(false);

        if (!originalVersionId) {
            onVideoVariantChange && onVideoVariantChange(null);
            if (videoRef.current) {
                videoRef.current.pause();
                videoRef.current.load();
            }
            return;
        }

        await handleVersionSelect(originalVersionId);
    };

    const handleTrim = async ({ trimStart, trimEnd, removeRanges }) => {
        setIsTrimming(true);
        setEditError(null);
        const trimSourceFilename = extractFilenameFromVideoUrl(trimDialogVideoUrl || currentVideoUrl);
        try {
            const res = await fetch(getApiUrl('/api/trim'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    input_filename: trimSourceFilename,
                    trim_start: trimStart,
                    trim_end: trimEnd,
                    remove_ranges: removeRanges || [],
                })
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            applyClipResponse(data);
            setShowTrimModal(false);
            setTrimDialogVideoUrl('');
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsTrimming(false);
        }
    };

    const openTrimModal = () => {
        setTrimDialogVideoUrl(currentVideoUrl);
        setShowTrimModal(true);
    };

    const handleApplySubtitleDefaultsToJob = (options) => {
        if (!onApplySubtitleDefaultsToJob) return;
        const nextY = Number(options?.yPosition);
        const fallbackY = Number(subtitleStyle?.yPosition ?? 86);
        const resolvedY = Number.isFinite(nextY) ? nextY : (Number.isFinite(fallbackY) ? fallbackY : 86);
        onApplySubtitleDefaultsToJob({
            position: options?.position || subtitleStyle?.position || 'bottom',
            yPosition: resolvedY,
            fontSize: Number(options?.fontSize ?? subtitleStyle?.fontSize ?? 24),
            fontFamily: options?.fontFamily || subtitleStyle?.fontFamily,
            backgroundStyle: options?.backgroundStyle || subtitleStyle?.backgroundStyle,
        });
        setEditError('Untertitel-Vorgaben für alle Clips dieses Jobs gesetzt.');
        setTimeout(() => setEditError(null), 2500);
    };

    const handleApplyHookDefaultsToJob = (hookData) => {
        if (!onApplyHookDefaultsToJob) return;
        const payload = typeof hookData === 'string'
            ? { text: hookData, xPosition: 50, yPosition: 12, textAlign: 'center', size: 'M', widthPreset: 'wide' }
            : (hookData || {});
        onApplyHookDefaultsToJob({
            position: payload.position,
            horizontalPosition: payload.horizontalPosition,
            xPosition: payload.xPosition,
            yPosition: payload.yPosition,
            textAlign: payload.textAlign,
            size: payload.size,
            widthPreset: payload.widthPreset,
            fontFamily: payload.fontFamily,
            backgroundStyle: payload.backgroundStyle,
        });
        setEditError('Hook-Vorgaben für alle Clips dieses Jobs gesetzt.');
        setTimeout(() => setEditError(null), 2500);
    };

    const buildSubtitleSettingsPayload = () => {
        const fallbackPosition = (subtitleStyle?.position || 'bottom').toLowerCase();
        const normalizedPosition = fallbackPosition === 'center' ? 'middle' : fallbackPosition;
        const yPosition = Number(subtitleStyle?.yPosition);
        const fontSize = Number(subtitleStyle?.fontSize);
        return {
            position: ['top', 'middle', 'bottom'].includes(normalizedPosition) ? normalizedPosition : 'bottom',
            y_position: Number.isFinite(yPosition) ? Math.max(0, Math.min(100, yPosition)) : undefined,
            font_size: Number.isFinite(fontSize) ? Math.max(10, Math.min(120, Math.round(fontSize))) : 24,
            font_family: subtitleStyle?.fontFamily,
            background_style: subtitleStyle?.backgroundStyle,
        };
    };

    const buildHookSettingsPayload = (hookText) => {
        const x = Number(hookStyle?.xPosition);
        const y = Number(hookStyle?.yPosition);
        const xPosition = Number.isFinite(x) ? Math.max(0, Math.min(100, x)) : 50;
        const yPosition = Number.isFinite(y) ? Math.max(0, Math.min(100, y)) : 12;
        const fallbackPosition = yPosition < 34 ? 'top' : yPosition > 66 ? 'bottom' : 'center';
        const fallbackHorizontal = xPosition < 34 ? 'left' : xPosition > 66 ? 'right' : 'center';
        const position = (hookStyle?.position || fallbackPosition).toLowerCase();
        const horizontalPosition = (hookStyle?.horizontalPosition || fallbackHorizontal).toLowerCase();
        const textAlign = (hookStyle?.textAlign || horizontalPosition || 'center').toLowerCase();
        return {
            text: hookText,
            position: ['top', 'center', 'bottom'].includes(position) ? position : fallbackPosition,
            horizontal_position: ['left', 'center', 'right'].includes(horizontalPosition) ? horizontalPosition : fallbackHorizontal,
            x_position: xPosition,
            y_position: yPosition,
            text_align: ['left', 'center', 'right'].includes(textAlign) ? textAlign : 'center',
            size: ['S', 'M', 'L'].includes(hookStyle?.size) ? hookStyle.size : 'M',
            width_preset: hookStyle?.widthPreset || 'wide',
            font_family: hookStyle?.fontFamily,
            background_style: hookStyle?.backgroundStyle,
        };
    };

    const handleRenderClip = async () => {
        setIsRenderingClip(true);
        setEditError(null);
        try {
            const res = await fetch(getApiUrl('/api/clip/render'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    apply_tight_edit: true,
                    tight_edit_preset: tightEditPreset || 'aggressive',
                    apply_subtitles: true,
                    apply_hook: true,
                })
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            applyClipResponse(data);
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 6000);
        } finally {
            setIsRenderingClip(false);
        }
    };

    const handleQuickRenderWithDefaults = async () => {
        const hookText = String(resolvedHookDraftText || '').trim();
        if (!hookText) {
            setEditError('Hook-Text darf nicht leer sein.');
            return;
        }

        setIsRenderingClip(true);
        setEditError(null);
        onHookDraftChange && onHookDraftChange(hookText);
        try {
            const res = await fetch(getApiUrl('/api/clip/render/viral-original'), {
                method: 'POST',
                headers: buildLlmHeaders(),
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    apply_tight_edit: true,
                    tight_edit_preset: tightEditPreset || 'aggressive',
                    apply_subtitles: true,
                    subtitle_settings: buildSubtitleSettingsPayload(),
                    apply_hook: true,
                    hook_settings: buildHookSettingsPayload(hookText),
                    apply_stock_overlay: applyStockOverlay,
                })
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            applyClipResponse(data);
            if (data?.warning) {
                setEditError(data.warning);
                setTimeout(() => setEditError(null), 5000);
            }
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 6000);
        } finally {
            setIsRenderingClip(false);
        }
    };

    const handlePreviewRender = async ({ applySubtitles = true, applyHook = true, quiet = false } = {}) => {
        setIsPreviewRendering(true);
        if (!quiet) setEditError(null);
        try {
            const res = await fetch(getApiUrl('/api/clip/preview/render'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    apply_tight_edit: false,
                    tight_edit_preset: tightEditPreset || 'aggressive',
                    apply_subtitles: applySubtitles,
                    apply_hook: applyHook,
                })
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            applyClipResponse(data);
        } catch (e) {
            if (!quiet) {
                setEditError(e.message);
                setTimeout(() => setEditError(null), 6000);
                return;
            }
            throw e;
        } finally {
            setIsPreviewRendering(false);
        }
    };

    const handlePost = async () => {
        if (!uploadPostKey || !resolvedUploadUserId) {
            setPostResult({ success: false, status: 'failed', message: "API-Key oder User-ID fehlt.", platform_results: [] });
            return;
        }

        const selectedPlatforms = Object.keys(platforms).filter(k => platforms[k]);
        if (selectedPlatforms.length === 0) {
            setPostResult({ success: false, status: 'failed', message: "Mindestens eine Plattform auswählen.", platform_results: [] });
            return;
        }

        if (selectedPlatforms.includes('pinterest') && !pinterestBoardId.trim()) {
            setPostResult({ success: false, status: 'failed', message: "Pinterest benötigt eine Board-ID.", platform_results: [] });
            return;
        }

        if (isScheduling && !scheduleDate) {
            setPostResult({ success: false, status: 'failed', message: "Bitte Datum und Uhrzeit auswählen.", platform_results: [] });
            return;
        }

        setPosting(true);
        setPostResult(null);
        stopPostStatusPolling();

        try {
            const payload = {
                job_id: jobId,
                clip_index: clipIndex,
                api_key: uploadPostKey,
                user_id: resolvedUploadUserId,
                platforms: selectedPlatforms,
                title: postTitle,
                description: postDescription,
                first_comment: firstComment,
                instagram_share_mode: instagramShareMode,
                instagram_collaborators: String(instagramCollaborators || '').trim(),
                tiktok_post_mode: tiktokPostMode,
                tiktok_is_aigc: tiktokIsAigc,
                facebook_page_id: facebookPageId,
                pinterest_board_id: pinterestBoardId,
            };

            if (isScheduling && scheduleDate) {
                // Convert to ISO-8601
                payload.scheduled_date = new Date(scheduleDate).toISOString();
                // Optional: pass timezone if needed, backend defaults to UTC or we can send user's timezone
                payload.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
            }

            const res = await fetch(getApiUrl('/api/social/post'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            setPostResult(data);
            applyClipResponse(data);

            if (shouldPollPostStatus(data)) {
                postStatusTimeoutRef.current = window.setTimeout(() => {
                    refreshPostStatus(data, { silent: true });
                }, POST_STATUS_POLL_INTERVAL_MS);
            }

        } catch (e) {
            setPostResult({
                success: false,
                status: 'failed',
                message: `Fehlgeschlagen: ${e.message}`,
                platform_results: [],
                requested_platforms: selectedPlatforms,
                scheduled: isScheduling,
            });
        } finally {
            setPosting(false);
        }
    };

    const handleRetryPlatform = async (platform, retryMode) => {
        if (!uploadPostKey || !resolvedUploadUserId) {
            setPostResult((prev) => prev ? {
                ...prev,
                poll_error: 'API-Key oder User-ID fehlt.',
            } : {
                success: false,
                status: 'failed',
                message: 'API-Key oder User-ID fehlt.',
                platform_results: [],
            });
            return;
        }

        setRetryingPlatformAction(`${platform}:${retryMode}`);
        stopPostStatusPolling();

        try {
            const res = await fetch(getApiUrl('/api/social/post/retry'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    api_key: uploadPostKey,
                    user_id: resolvedUploadUserId,
                    platform,
                    retry_mode: retryMode,
                })
            });

            if (!res.ok) {
                throw new Error(await readErrorText(res));
            }

            const data = await res.json();
            setPostResult(data);
            applyClipResponse(data);

            if (shouldPollPostStatus(data)) {
                postStatusTimeoutRef.current = window.setTimeout(() => {
                    refreshPostStatus(data, { silent: true });
                }, POST_STATUS_POLL_INTERVAL_MS);
            }
        } catch (e) {
            setPostResult((prev) => prev ? {
                ...prev,
                poll_error: `${getPlatformLabel(platform)} Retry fehlgeschlagen: ${e.message}`,
            } : {
                success: false,
                status: 'failed',
                message: e.message,
                platform_results: [],
            });
        } finally {
            setRetryingPlatformAction('');
        }
    };

    const handleReplayFromStart = () => {
        if (!videoRef.current) return;
        const startTime = isPreviewOnly ? previewStart : 0;
        videoRef.current.currentTime = startTime;
        const playPromise = videoRef.current.play();
        if (playPromise && typeof playPromise.catch === 'function') {
            playPromise.catch(() => {});
        }
    };

    return (
        <div className={`bg-surface border rounded-2xl overflow-hidden flex flex-col group transition-all animate-[fadeIn_0.5s_ease-out] min-h-[300px] h-auto ${
            clipPostHighlight?.cardClass || 'border-white/5 hover:border-white/10'
        }`} style={{ animationDelay: `${index * 0.1}s` }}>
            {/* Top: Video Preview (Full Width) */}
            <div className={`w-full p-3 ${clipPostHighlight?.previewClass || 'bg-black/40 border-b border-white/5'}`}>
                <div className="mx-auto w-full max-w-[360px] aspect-[9/16] bg-black rounded-xl overflow-hidden relative group/video">
                <video
                    ref={videoRef}
                    src={currentVideoUrl}
                    controls
                    className="w-full h-full object-contain"
                    playsInline
                    preload="metadata"
                    onLoadedMetadata={() => {
                        if (isPreviewOnly && videoRef.current) {
                            videoRef.current.currentTime = previewStart;
                        }
                    }}
                    onSeeking={() => {
                        if (!videoRef.current || !isPreviewOnly) return;
                        const current = videoRef.current.currentTime;
                        if (current < previewStart || current >= previewEnd) {
                            videoRef.current.currentTime = previewStart;
                        }
                    }}
                    onTimeUpdate={() => {
                        if (!videoRef.current) return;
                        if (isPreviewOnly && videoRef.current.currentTime < previewStart) {
                            videoRef.current.currentTime = previewStart;
                            return;
                        }
                        if (isPreviewOnly && videoRef.current.currentTime >= previewEnd) {
                            videoRef.current.pause();
                            videoRef.current.currentTime = previewStart;
                            return;
                        }
                    }}
                    onPlay={() => {
                        if (videoRef.current && isPreviewOnly) {
                            const current = videoRef.current.currentTime;
                            if (current < previewStart || current >= previewEnd) {
                                videoRef.current.currentTime = previewStart;
                            }
                        }
                        const currentTime = videoRef.current ? videoRef.current.currentTime : 0;
                        onPlay && onPlay(isPreviewOnly ? currentTime : (clip.start + currentTime));
                    }}
                    onPause={() => onPause && onPause()}
                    onEnded={() => {
                        if (videoRef.current) {
                            videoRef.current.currentTime = isPreviewOnly ? previewStart : 0;
                            videoRef.current.play();
                        }
                    }}
                />
                <div className="absolute top-3 left-3 flex gap-2">
                    <span className="bg-black/60 backdrop-blur-md text-white text-[10px] font-bold px-2 py-1 rounded-md border border-white/10 uppercase tracking-wide">
                        Clip {index + 1}
                    </span>
                    {isPreviewOnly && (
                            <span className="bg-cyan-500/20 backdrop-blur-md text-cyan-200 text-[10px] font-bold px-2 py-1 rounded-md border border-cyan-400/30 uppercase tracking-wide">
                            Vorschau-Entwurf
                        </span>
                    )}
                </div>
                <button
                    type="button"
                    onClick={handleReplayFromStart}
                    className="absolute top-3 right-3 bg-black/60 hover:bg-black/75 backdrop-blur-md text-white text-[10px] font-bold px-2 py-1 rounded-md border border-white/10 uppercase tracking-wide flex items-center gap-1"
                >
                    <RotateCcw size={11} /> Von vorne
                </button>

                {/* Auto Edit Overlay if Processing */}
                {isEditing && (
                    <div className="absolute inset-0 bg-black/60 backdrop-blur-sm flex flex-col items-center justify-center z-10 p-4 text-center">
                        <Loader2 size={32} className="text-primary animate-spin mb-3" />
                        <span className="text-xs font-bold text-white uppercase tracking-wider">KI-Bearbeitung läuft...</span>
                        <span className="text-[10px] text-zinc-400 mt-1">Virale Edits & Zooms werden angewendet</span>
                    </div>
                )}
                </div>
            </div>

            {/* Bottom: Content & Details */}
            <div className={`flex-1 p-4 md:p-5 flex flex-col overflow-y-auto md:overflow-hidden custom-scrollbar touch-scroll min-w-0 ${
                clipPostHighlight?.contentClass || 'bg-[#121214]'
            }`}>
                <div className="mb-4 space-y-3">
                    <div className="flex items-start gap-3">
                        <label className="mt-0.5 flex shrink-0 items-center">
                            <input
                                type="checkbox"
                                checked={!!isSelected}
                                onChange={() => onToggleSelect && onToggleSelect()}
                                className="h-4 w-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                            />
                        </label>
                        <div className="min-w-0 flex-1">
                            <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0 flex-1">
                                    <input
                                        type="text"
                                        value={titleDraft}
                                        onChange={(e) => setTitleDraft(e.target.value)}
                                        onBlur={persistClipTextMetadata}
                                        className="w-full rounded-lg border border-white/10 bg-black/35 px-3 py-2 text-sm font-bold text-white focus:outline-none focus:border-primary/50"
                                        placeholder="Titel fuer YouTube Shorts"
                                    />
                                </div>
                                <div className="flex shrink-0 flex-wrap justify-end gap-2">
                                    {clipPostHighlight && (
                                        <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${clipPostHighlight.badgeClass}`}>
                                            {clipPostHighlight.label}
                                        </span>
                                    )}
                                    <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                                        isSelected
                                            ? 'border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-200'
                                            : 'border-white/10 bg-white/5 text-zinc-500'
                                    }`}>
                                        {isSelected ? 'Ausgewaehlt' : 'Auswaehlbar'}
                                    </span>
                                </div>
                            </div>
                            <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-zinc-500 font-mono">
                                <span className="bg-white/5 px-1.5 py-0.5 rounded border border-white/5 shrink-0">{Math.round(clipDuration)}s</span>
                                <span className="bg-white/5 px-1.5 py-0.5 rounded border border-white/5 shrink-0">#shorts</span>
                                <span className="bg-white/5 px-1.5 py-0.5 rounded border border-white/5 shrink-0">#viral</span>
                                {textMetadataStatus && (
                                    <span className={`px-1.5 py-0.5 rounded border shrink-0 ${
                                        textMetadataStatus.type === 'error'
                                            ? 'border-red-500/20 bg-red-500/10 text-red-300'
                                            : textMetadataStatus.type === 'success'
                                                ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'
                                                : 'border-white/10 bg-white/5 text-zinc-400'
                                    }`}>
                                        {textMetadataStatus.message}
                                    </span>
                                )}
                            </div>
                        </div>
                    </div>

                    <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                        <div className="mb-3">
                            <div className="mb-2 flex items-center justify-between gap-3">
                                <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">Beschreibung</span>
                                <span className="text-[10px] text-zinc-500">Wird fuer TikTok und Instagram gemeinsam gespeichert</span>
                            </div>
                            <textarea
                                value={descriptionDraft}
                                onChange={(e) => setDescriptionDraft(e.target.value)}
                                onBlur={persistClipTextMetadata}
                                rows={3}
                                className="w-full resize-y rounded-lg border border-white/10 bg-black/40 p-3 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-primary/50"
                                placeholder="Kurz, klar, klickstark..."
                            />
                        </div>
                        <div className="mb-2 flex items-center justify-between gap-3">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">Hook-Entwurf</span>
                            <span className="text-[10px] text-zinc-500">Wird fuer Schnell-Render und Bulk-Planung genutzt</span>
                        </div>
                        <textarea
                            value={resolvedHookDraftText}
                            onChange={(e) => onHookDraftChange && onHookDraftChange(e.target.value)}
                            rows={3}
                            readOnly={!onHookDraftChange}
                            className="w-full resize-y rounded-lg border border-white/10 bg-black/40 p-3 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-primary/50"
                            placeholder="Kurzer, reisserischer Hook..."
                        />
                    </div>
                </div>

                <div className="mb-4 p-3 bg-black/20 rounded-lg border border-white/5">
                    <div className="flex items-center justify-between gap-3 mb-2">
                        <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Versionen</span>
                        <span className="text-[10px] text-zinc-500 font-mono">
                            {clipVersions.length ? `${clipVersions.length} Versionen` : 'Original'}
                        </span>
                    </div>
                    {clipVersions.length > 1 ? (
                        <select
                            value={activeVersionId}
                            onChange={(e) => handleVersionSelect(e.target.value)}
                            disabled={isBusy}
                            className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-primary/50"
                        >
                            {clipVersions.map((version) => (
                                <option key={version.id} value={version.id}>
                                    {`V${version.version} · ${version.label}`}
                                </option>
                            ))}
                        </select>
                    ) : (
                        <div className="text-xs text-zinc-400">
                            {clipVersions[0]?.label || (isPreviewOnly ? 'Entwurf (noch nicht gerendert)' : 'Original')}
                        </div>
                    )}
                </div>

                <div className="mb-4 rounded-lg border border-white/5 bg-black/20 p-3">
                    <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                        <Youtube size={12} className="text-red-400" />
                        <span>Copy-Vorschau</span>
                    </div>
                    <p className="text-xs text-zinc-300 break-words">
                        {titleDraft || "Viraler Clip erzeugt"}
                    </p>
                    <p className="mt-2 text-xs text-zinc-500 break-words">
                        {descriptionDraft || "Noch keine Beschreibung gesetzt."}
                    </p>
                </div>

                {/* Error Message */}
                {editError && (
                    <div className="mb-3 p-2 bg-red-500/10 border border-red-500/20 text-red-400 text-[10px] rounded-lg flex items-center gap-2">
                        <AlertCircle size={12} className="shrink-0" />
                        {editError}
                    </div>
                )}

                {/* Actions Footer */}
                {isPreviewOnly && (
                    <div className="mb-3 rounded-lg border border-cyan-400/20 bg-cyan-500/10 px-3 py-2 text-[11px] text-cyan-100">
                        Vorschau-Modus: Untertitel/Hook können als Stil gespeichert werden. <b>Vorschau-Render</b> rendert absichtlich nur ein kurzes 1s-Sample (Turbo) zur Positionierung, danach <b>Final-Render</b>.
                    </div>
                )}
                <div className="mt-auto pt-4 border-t border-white/5">
                    <div className="grid grid-cols-2 gap-3">
                        <button
                            type="button"
                            onClick={handleQuickRenderWithDefaults}
                            disabled={isBusy}
                            className="py-2 bg-gradient-to-r from-fuchsia-600 to-pink-600 hover:from-fuchsia-500 hover:to-pink-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-fuchsia-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2 disabled:opacity-60"
                        >
                            {isRenderingClip ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                            {isRenderingClip ? 'Rendern...' : 'Schnell-Render'}
                        </button>
                        <button
                            onClick={() => setShowModal(true)}
                            disabled={isPreviewOnly}
                            className="py-2 bg-primary hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-xs font-bold shadow-lg shadow-primary/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2"
                        >
                            <Share2 size={14} className="shrink-0" /> Posten
                        </button>
                    </div>

                    <button
                        type="button"
                        onClick={() => setShowMoreOptions((prev) => !prev)}
                        className="mt-3 inline-flex w-full items-center justify-between rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-zinc-200 hover:bg-white/10"
                    >
                        <span>Weitere Optionen</span>
                        <ChevronDown size={14} className={`transition-transform ${showMoreOptions ? 'rotate-180' : ''}`} />
                    </button>

                    {showMoreOptions && (
                        <div className="mt-3 grid grid-cols-2 gap-3">
                            <div className="col-span-2 rounded-lg border border-white/10 bg-black/20 p-3">
                                <div className="mb-2 flex items-center justify-between gap-3">
                                    <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">Instagram-Collaborator</span>
                                    <span className="text-[10px] text-zinc-500">Leer = Job-Default, empfohlen ohne @</span>
                                </div>
                                <div className="flex flex-col gap-2 md:flex-row">
                                    <input
                                        type="text"
                                        value={instagramCollaboratorsDraft}
                                        onChange={(e) => setInstagramCollaboratorsDraft(e.target.value)}
                                        onBlur={persistClipTextMetadata}
                                        className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-primary/50"
                                        placeholder={resolvedJobInstagramCollaborators ? `Job-Default (ohne @): ${resolvedJobInstagramCollaborators}` : 'Optional, ohne @, z. B. partner_account'}
                                    />
                                    <button
                                        type="button"
                                        onClick={handleApplyCollaboratorsToJob}
                                        disabled={isApplyingJobCollaborators}
                                        className="inline-flex items-center justify-center rounded-lg border border-cyan-400/20 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/15 disabled:opacity-60"
                                    >
                                        {isApplyingJobCollaborators ? 'Speichert...' : 'Fuer alle uebernehmen'}
                                    </button>
                                </div>
                                <p className="mt-2 text-[11px] text-zinc-500">
                                    Mit oder ohne `@` moeglich, empfohlen ohne `@`. Der Button setzt den aktuellen Wert dieser Card global fuer den ganzen Job.
                                </p>
                            </div>

                            {isPreviewOnly && (
                                <button
                                    onClick={() => handlePreviewRender()}
                                    disabled={isBusy}
                                    className="col-span-2 py-2 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-emerald-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2 disabled:opacity-60"
                                >
                                    {isPreviewRendering ? <Loader2 size={14} className="animate-spin" /> : <Video size={14} />}
                                    {isPreviewRendering ? 'Vorschau wird gerendert...' : 'Vorschau-Render (1s Turbo)'}
                                </button>
                            )}
                            {isPreviewOnly && (
                                <button
                                    onClick={handleRenderClip}
                                    disabled={isBusy}
                                    className="col-span-2 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-cyan-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2 disabled:opacity-60"
                                >
                                    {isRenderingClip ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                                    {isRenderingClip ? 'Rendern...' : 'Final-Render (Version erstellen)'}
                                </button>
                            )}

                            <div className="col-span-2 flex items-center gap-2">
                                <label className="flex items-center gap-2 text-xs text-zinc-400">
                                    <input
                                        type="checkbox"
                                        checked={applyStockOverlay}
                                        onChange={(e) => setApplyStockOverlay(e.target.checked)}
                                        className="h-3 w-3 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                    />
                                    Stock-Overlay aktivieren
                                </label>
                            </div>

                            <button
                                onClick={handleAutoEdit}
                                disabled={isBusy || isPreviewOnly}
                                className="py-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-purple-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2"
                            >
                                {isEditing ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                                {isEditing ? 'Bearbeite...' : 'Auto-Schnitt'}
                            </button>

                            <button
                                onClick={() => setShowSubtitleModal(true)}
                                disabled={isBusy}
                                className="py-2 bg-gradient-to-r from-yellow-600 to-orange-600 hover:from-yellow-500 hover:to-orange-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-orange-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2"
                            >
                                {isSubtitling ? <Loader2 size={14} className="animate-spin" /> : <Type size={14} />}
                                {isSubtitling ? 'Füge ein...' : (isPreviewOnly ? 'Untertitel-Stil speichern' : 'Untertitel')}
                            </button>

                            <button
                                onClick={() => setShowHookModal(true)}
                                disabled={isBusy}
                                className="py-2 bg-gradient-to-r from-amber-400 to-yellow-500 hover:from-amber-300 hover:to-yellow-400 text-black rounded-lg text-xs font-bold shadow-lg shadow-yellow-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2"
                            >
                                {isHooking ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                                {isHooking ? 'Füge ein...' : (isPreviewOnly ? 'Hook-Stil speichern' : 'Viraler Hook')}
                            </button>

                            <button
                                onClick={openTrimModal}
                                disabled={isBusy || isPreviewOnly}
                                className="py-2 bg-gradient-to-r from-blue-500 to-cyan-600 hover:from-blue-400 hover:to-cyan-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-cyan-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2"
                            >
                                {isTrimming ? <Loader2 size={14} className="animate-spin" /> : <Scissors size={14} />}
                                {isTrimming ? 'Schneide...' : 'Zuschneiden'}
                            </button>

                            <button
                                onClick={() => setShowTranslateModal(true)}
                                disabled={isBusy || isPreviewOnly}
                                className="py-2 bg-gradient-to-r from-green-500 to-teal-600 hover:from-green-400 hover:to-teal-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-green-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2"
                            >
                                {isTranslating ? <Loader2 size={14} className="animate-spin" /> : <Languages size={14} />}
                                {isTranslating ? 'Übersetze...' : 'Stimmen-Dub'}
                            </button>

                            <button
                                onClick={async (e) => {
                                    e.preventDefault();
                                    try {
                                        const response = await fetch(currentVideoUrl);
                                        if (!response.ok) throw new Error('Download failed');
                                        const blob = await response.blob();
                                        const url = window.URL.createObjectURL(blob);
                                        const a = document.createElement('a');
                                        a.style.display = 'none';
                                        a.href = url;
                                        a.download = `clip-${index + 1}.mp4`;
                                        document.body.appendChild(a);
                                        a.click();
                                        window.URL.revokeObjectURL(url);
                                        document.body.removeChild(a);
                                    } catch (err) {
                                        console.error('Download error:', err);
                                        window.open(currentVideoUrl, '_blank');
                                    }
                                }}
                                disabled={isPreviewOnly}
                                className="py-2 bg-white/5 hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed text-zinc-300 hover:text-white rounded-lg text-xs font-medium transition-colors flex items-center justify-center gap-2 border border-white/5 truncate px-2"
                            >
                                <Download size={14} className="shrink-0" /> Herunterladen
                            </button>

                            <button
                                onClick={restoreOriginalVersion}
                                disabled={!isModifiedVideo || isBusy || isPreviewOnly}
                                className="col-span-2 py-2 bg-black/30 hover:bg-black/50 disabled:opacity-40 disabled:cursor-not-allowed text-zinc-300 hover:text-white rounded-lg text-xs font-medium transition-colors flex items-center justify-center gap-2 border border-white/5 truncate px-2"
                            >
                                <RotateCcw size={14} className="shrink-0" /> Original wiederherstellen
                            </button>
                        </div>
                    )}
                </div>
            </div>

            {/* Post Modal */}
            {showModal && (
                createPortal(
                <div className="fixed inset-0 z-[1000] flex items-start md:items-center justify-center p-3 md:p-4 bg-black/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out] overflow-y-auto touch-scroll">
                    <div className="bg-[#121214] border border-white/10 p-6 rounded-2xl w-full max-w-md shadow-2xl relative my-4 md:my-0 max-h-[calc(100dvh-1.5rem)] md:max-h-[90vh] overflow-y-auto custom-scrollbar touch-scroll">
                        <button
                            onClick={() => setShowModal(false)}
                            className="absolute top-4 right-4 text-zinc-500 hover:text-white"
                        >
                            <X size={20} />
                        </button>

                        <h3 className="text-lg font-bold text-white mb-4">Posten / Planen</h3>

                        <div className="mb-4 rounded-lg border border-white/5 bg-white/5 px-3 py-2 text-xs text-zinc-400">
                            Aktives Profil: <span className="text-white font-medium">{activeUploadProfile || uploadUserId || 'Kein Profil ausgewählt'}</span>
                        </div>

                        {!uploadPostKey && (
                            <div className="mb-4 p-3 bg-yellow-500/10 border border-yellow-500/20 text-yellow-200 text-xs rounded-lg flex items-start gap-2">
                                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                                <div>Bitte zuerst API-Key in den Einstellungen setzen.</div>
                            </div>
                        )}

                        <div className="space-y-4 mb-6">
                            {/* Title & Description */}
                            <div>
                                <label className="block text-xs font-bold text-zinc-400 mb-1">Video-Titel</label>
                                <input
                                    type="text"
                                    value={postTitle}
                                    onChange={(e) => setPostTitle(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50 placeholder-zinc-600"
                                    placeholder="Einen starken Titel eingeben..."
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-bold text-zinc-400 mb-1">Beschreibung</label>
                                <textarea
                                    value={postDescription}
                                    onChange={(e) => setPostDescription(e.target.value)}
                                    rows={4}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50 placeholder-zinc-600 resize-none"
                                    placeholder="Beschreibung für den Post schreiben..."
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-bold text-zinc-400 mb-1">Erster Kommentar (optional)</label>
                                <textarea
                                    value={firstComment}
                                    onChange={(e) => setFirstComment(e.target.value)}
                                    rows={3}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50 placeholder-zinc-600 resize-none"
                                    placeholder="Wird gesendet, wo Upload-Post erste Kommentare unterstützt."
                                />
                            </div>

                            {/* Scheduling */}
                            <div className="p-3 bg-white/5 rounded-lg border border-white/5">
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-2 text-sm text-white font-medium">
                                        <Calendar size={16} className="text-purple-400" /> Post planen
                                    </div>
                                    <label className="relative inline-flex items-center cursor-pointer">
                                        <input type="checkbox" checked={isScheduling} onChange={(e) => setIsScheduling(e.target.checked)} className="sr-only peer" />
                                        <div className="w-9 h-5 bg-zinc-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-600"></div>
                                    </label>
                                </div>

                                {isScheduling && (
                                    <div className="mt-3 animate-[fadeIn_0.2s_ease-out]">
                                        <label className="block text-xs text-zinc-400 mb-1">Datum & Uhrzeit wählen</label>
                                        <div className="relative">
                                            <input
                                                type="datetime-local"
                                                value={scheduleDate}
                                                onChange={(e) => setScheduleDate(e.target.value)}
                                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 pl-9 text-sm text-white focus:outline-none focus:border-purple-500/50 [color-scheme:dark]"
                                            />
                                            <Clock size={14} className="absolute left-3 top-2.5 text-zinc-500" />
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Platforms */}
                            <div>
                                <label className="block text-xs font-bold text-zinc-400 mb-2">Plattformen auswählen</label>
                                <div className="grid grid-cols-1 gap-2">
                                    {SOCIAL_PLATFORM_OPTIONS.map((platform) => (
                                        <label key={platform.key} className="flex items-center gap-3 p-3 bg-white/5 rounded-lg cursor-pointer hover:bg-white/10 transition-colors border border-white/5">
                                            <input
                                                type="checkbox"
                                                checked={!!platforms[platform.key]}
                                                onChange={e => setPlatforms({ ...platforms, [platform.key]: e.target.checked })}
                                                className="w-4 h-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                            />
                                            <div className="flex items-center gap-2 text-sm text-white">
                                                {platform.key === 'tiktok' ? <Video size={16} className="text-cyan-400" /> : null}
                                                {platform.key === 'instagram' ? <Instagram size={16} className="text-pink-400" /> : null}
                                                {platform.key === 'youtube' ? <Youtube size={16} className="text-red-400" /> : null}
                                                <span>{platform.label}</span>
                                            </div>
                                        </label>
                                    ))}
                                </div>
                            </div>

                            {platforms.instagram && (
                                <div className="p-3 bg-white/5 rounded-lg border border-white/5">
                                    <label className="block text-xs font-bold text-zinc-400 mb-2">Instagram-Share-Mode</label>
                                    <select
                                        value={instagramShareMode}
                                        onChange={(e) => setInstagramShareMode(e.target.value)}
                                        className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                    >
                                        {INSTAGRAM_SHARE_MODES.map((mode) => (
                                            <option key={mode.value} value={mode.value}>
                                                {mode.label}
                                            </option>
                                        ))}
                                    </select>
                                    <p className="mt-2 text-[11px] text-zinc-500 leading-relaxed">
                                        {INSTAGRAM_SHARE_MODES.find((mode) => mode.value === instagramShareMode)?.description}
                                    </p>
                                    <div className="mt-3">
                                        <label className="block text-xs font-bold text-zinc-400 mb-2">Collaborator (optional)</label>
                                        <input
                                            type="text"
                                            value={instagramCollaborators}
                                            onChange={(e) => setInstagramCollaborators(e.target.value)}
                                            className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                            placeholder={resolvedJobInstagramCollaborators ? `Job-Default (ohne @): ${resolvedJobInstagramCollaborators}` : 'Ohne @, z. B. partner_account'}
                                        />
                                        <p className="mt-2 text-[11px] text-zinc-500 leading-relaxed">
                                            Optional. Mit oder ohne `@` moeglich, empfohlen ohne `@`. Leer = Job-Default.
                                        </p>
                                    </div>
                                    <p className="mt-2 text-[11px] text-zinc-600 leading-relaxed">
                                        Upload-Post nutzt das eingebettete Original-Audio. Der Text für Instagram wird über das Reel-Titel-Feld gesendet, nicht über das globale Beschreibungsfeld.
                                    </p>
                                </div>
                            )}

                            {platforms.tiktok && (
                                <div className="p-3 bg-white/5 rounded-lg border border-white/5 space-y-3">
                                    <div>
                                        <label className="block text-xs font-bold text-zinc-400 mb-2">TikTok-Post-Mode</label>
                                        <select
                                            value={tiktokPostMode}
                                            onChange={(e) => setTiktokPostMode(e.target.value)}
                                            className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                        >
                                            {TIKTOK_POST_MODES.map((mode) => (
                                                <option key={mode.value} value={mode.value}>{mode.label}</option>
                                            ))}
                                        </select>
                                        <p className="mt-2 text-[11px] text-zinc-500 leading-relaxed">
                                            {TIKTOK_POST_MODES.find((mode) => mode.value === tiktokPostMode)?.description}
                                        </p>
                                    </div>
                                    <label className="flex items-center gap-3 text-sm text-zinc-300">
                                        <input
                                            type="checkbox"
                                            checked={tiktokIsAigc}
                                            onChange={(e) => setTiktokIsAigc(e.target.checked)}
                                            className="w-4 h-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                        />
                                        Diesen TikTok-Upload als KI-generiert markieren
                                    </label>
                                </div>
                            )}

                            {platforms.facebook && (
                                <div className="p-3 bg-white/5 rounded-lg border border-white/5">
                                    <label className="block text-xs font-bold text-zinc-400 mb-2">Facebook-Page-ID</label>
                                    <input
                                        type="text"
                                        value={facebookPageId}
                                        onChange={(e) => setFacebookPageId(e.target.value)}
                                        className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                        placeholder="Optional, wenn nur eine Seite verbunden ist"
                                    />
                                </div>
                            )}

                            {platforms.pinterest && (
                                <div className="p-3 bg-white/5 rounded-lg border border-white/5">
                                    <label className="block text-xs font-bold text-zinc-400 mb-2">Pinterest-Board-ID</label>
                                    <input
                                        type="text"
                                        value={pinterestBoardId}
                                        onChange={(e) => setPinterestBoardId(e.target.value)}
                                        className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                        placeholder="Für Pinterest von Upload-Post erforderlich"
                                    />
                                </div>
                            )}
                        </div>

                        {postResult && (
                            <div className={`mb-4 rounded-xl border p-3 ${
                                postResult.failure_count
                                    ? 'border-amber-500/20 bg-amber-500/10'
                                    : postResult.success === false
                                        ? 'border-red-500/20 bg-red-500/10'
                                        : postResult.pending_count
                                            ? 'border-cyan-500/20 bg-cyan-500/10'
                                            : 'border-green-500/20 bg-green-500/10'
                            }`}>
                                <div className="flex items-start gap-2 text-xs">
                                    {postResult.failure_count ? (
                                        <AlertCircle size={14} className="mt-0.5 shrink-0 text-amber-300" />
                                    ) : postResult.success === false ? (
                                        <AlertCircle size={14} className="mt-0.5 shrink-0 text-red-400" />
                                    ) : postResult.pending_count ? (
                                        <Loader2 size={14} className="mt-0.5 shrink-0 text-cyan-300 animate-spin" />
                                    ) : (
                                        <CheckCircle size={14} className="mt-0.5 shrink-0 text-green-400" />
                                    )}
                                    <div className="min-w-0 flex-1">
                                        <div className="font-semibold text-white">{postResult.message}</div>
                                        <div className="mt-1 text-[11px] text-zinc-300">
                                            Status: <span className="uppercase tracking-wide">{postResult.status || 'unbekannt'}</span>
                                            {' · '}
                                            Erfolgreich {postResult.success_count || 0}
                                            {' · '}
                                            Fehlgeschlagen {postResult.failure_count || 0}
                                            {' · '}
                                            Offen {postResult.pending_count || 0}
                                        </div>
                                        {(postResult.request_id || postResult.job_id) && (
                                            <div className="mt-1 text-[10px] text-zinc-400 break-all">
                                                {postResult.request_id ? `Request-ID: ${postResult.request_id}` : null}
                                                {postResult.request_id && postResult.job_id ? ' · ' : null}
                                                {postResult.job_id ? `Vendor-Job-ID: ${postResult.job_id}` : null}
                                            </div>
                                        )}
                                        {postResult.poll_error && (
                                            <div className="mt-1 text-[10px] text-red-300">{postResult.poll_error}</div>
                                        )}
                                    </div>
                                </div>

                                {!!displayPlatformResults.length && (
                                    <div className="mt-3 space-y-2">
                                        {displayPlatformResults.map((item) => {
                                            const statusValue = (item.status || '').toLowerCase();
                                            const isNotSelected = statusValue === 'not_selected';
                                            const isPending = !isNotSelected && item.success !== true && item.success !== false;
                                            const canRetryWithSchedule = Boolean(postResult?.request_settings?.scheduled_date);
                                            const isRetryingScheduled = retryingPlatformAction === `${item.platform}:scheduled`;
                                            const isRetryingNow = retryingPlatformAction === `${item.platform}:now`;
                                            const isRetryingThisPlatform = isRetryingScheduled || isRetryingNow;
                                            const rowClass = isNotSelected
                                                ? 'border-white/10 bg-black/20'
                                                : item.success === true
                                                ? 'border-green-500/20 bg-green-500/10'
                                                : item.success === false
                                                    ? 'border-red-500/20 bg-red-500/10'
                                                    : 'border-white/10 bg-white/5';
                                            return (
                                                <div key={`${item.platform}-${item.publish_id || item.post_id || item.message || 'pending'}`} className={`rounded-lg border px-3 py-2 ${rowClass}`}>
                                                    <div className="flex items-center justify-between gap-3">
                                                        <div className="text-xs font-semibold text-white">{getPlatformLabel(item.platform)}</div>
                                                        <div className="flex items-center gap-2 text-[11px]">
                                                            {item.success === true ? <CheckCircle size={13} className="text-green-400" /> : null}
                                                            {item.success === false ? <AlertCircle size={13} className="text-red-400" /> : null}
                                                            {isPending ? <Loader2 size={13} className="text-cyan-300 animate-spin" /> : null}
                                                            {isNotSelected ? <span className="text-zinc-500">-</span> : null}
                                                            <span className="uppercase tracking-wide text-zinc-300">
                                                                {isNotSelected ? 'nicht_ausgewählt' : (item.status || (isPending ? 'offen' : item.success ? 'erfolgreich' : 'fehlgeschlagen'))}
                                                            </span>
                                                        </div>
                                                    </div>
                                                    <div className="mt-1 text-[11px] text-zinc-300">
                                                        {item.message || item.error || (isPending ? 'Warte auf Rückmeldung von Upload-Post.' : (isNotSelected ? 'Nicht ausgewählt.' : 'Abgeschlossen'))}
                                                    </div>
                                                    {item.success === false && (
                                                        <div className="mt-2 flex flex-wrap gap-2">
                                                            {canRetryWithSchedule && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => handleRetryPlatform(item.platform, 'scheduled')}
                                                                    disabled={posting || isRefreshingPostStatus || isRetryingThisPlatform || !uploadPostKey || !resolvedUploadUserId}
                                                                    className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] text-white hover:bg-white/10 disabled:opacity-50"
                                                                >
                                                                    {isRetryingScheduled ? <Loader2 size={12} className="animate-spin" /> : <Calendar size={12} />}
                                                                    Mit Zeitplan
                                                                </button>
                                                            )}
                                                            <button
                                                                type="button"
                                                                onClick={() => handleRetryPlatform(item.platform, 'now')}
                                                                disabled={posting || isRefreshingPostStatus || isRetryingThisPlatform || !uploadPostKey || !resolvedUploadUserId}
                                                                className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] text-white hover:bg-white/10 disabled:opacity-50"
                                                            >
                                                                {isRetryingNow ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                                                                Sofort posten
                                                            </button>
                                                        </div>
                                                    )}
                                                    {(item.url || item.link) && (
                                                        <a
                                                            href={item.url || item.link}
                                                            target="_blank"
                                                            rel="noreferrer"
                                                            className="mt-2 inline-flex text-[11px] text-cyan-300 hover:text-cyan-200"
                                                        >
                                                            Post öffnen
                                                        </a>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}

                                {(postResult.request_id || postResult.job_id) && (
                                    <div className="mt-3 flex gap-2">
                                        <button
                                            type="button"
                                            onClick={() => refreshPostStatus(postResult)}
                                            disabled={isRefreshingPostStatus}
                                            className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[11px] text-white hover:bg-white/10 disabled:opacity-50"
                                        >
                                            {isRefreshingPostStatus ? <Loader2 size={12} className="animate-spin" /> : <Clock size={12} />}
                                            Status aktualisieren
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

                        <button
                            onClick={handlePost}
                            disabled={posting || !!retryingPlatformAction || !uploadPostKey || !resolvedUploadUserId}
                            className="w-full py-3 bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-white font-bold transition-all flex items-center justify-center gap-2"
                        >
                            {posting ? <><Loader2 size={16} className="animate-spin" /> {isScheduling ? 'Plane...' : 'Veröffentliche...'}</> : <><Share2 size={16} /> {isScheduling ? 'Post planen' : 'Jetzt veröffentlichen'}</>}
                        </button>
                    </div>
                </div>,
                document.body
                )
            )}

            <SubtitleModal
                isOpen={showSubtitleModal}
                onClose={() => setShowSubtitleModal(false)}
                onGenerate={handleSubtitle}
                onApplyAsJobDefault={handleApplySubtitleDefaultsToJob}
                isProcessing={isSubtitling}
                videoUrl={currentVideoUrl}
                defaultSettings={subtitleStyle}
            />

            <HookModal
                isOpen={showHookModal}
                onClose={() => setShowHookModal(false)}
                onGenerate={handleHook}
                onApplyAsJobDefault={handleApplyHookDefaultsToJob}
                isProcessing={isHooking}
                videoUrl={currentVideoUrl}
                initialText={resolvedHookDraftText}
                defaultSettings={hookStyle}
            />

            <TranslateModal
                isOpen={showTranslateModal}
                onClose={() => setShowTranslateModal(false)}
                onTranslate={handleTranslate}
                isProcessing={isTranslating}
                videoUrl={currentVideoUrl}
                hasApiKey={!!elevenLabsKey}
            />

            <TrimModal
                isOpen={showTrimModal}
                onClose={() => {
                    setShowTrimModal(false);
                    setTrimDialogVideoUrl('');
                }}
                onTrim={handleTrim}
                isProcessing={isTrimming}
                videoUrl={trimDialogVideoUrl || currentVideoUrl}
            />
        </div>
    );
}
