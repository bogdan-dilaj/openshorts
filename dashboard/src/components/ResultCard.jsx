import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Download, Share2, Instagram, Youtube, Video, CheckCircle, AlertCircle, X, Loader2, Copy, Wand2, Type, Calendar, Clock, Languages, RotateCcw, Scissors, Sparkles } from 'lucide-react';
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
                message: 'Warte auf Rueckmeldung von Upload-Post.',
            });
            continue;
        }
        rows.push({
            platform: key,
            success: null,
            status: 'not_selected',
            message: 'Nicht fuer diesen Post ausgewaehlt.',
        });
    }

    return rows;
};

export default function ResultCard({ clip, index, jobId, uploadPostKey, uploadUserId, geminiApiKey, llmProvider, ollamaBaseUrl, ollamaModel, elevenLabsKey, subtitleStyle, hookStyle, tightEditPreset, socialPostSettings = DEFAULT_SOCIAL_POST_SETTINGS, activeUploadProfile, currentVideoOverride, onVideoVariantChange, onClipUpdated, onPlay, onPause }) {
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

    const [platforms, setPlatforms] = useState({ ...DEFAULT_SOCIAL_POST_SETTINGS.platforms, ...(socialPostSettings.platforms || {}) });
    const [postTitle, setPostTitle] = useState("");
    const [postDescription, setPostDescription] = useState("");
    const [firstComment, setFirstComment] = useState("");
    const [isScheduling, setIsScheduling] = useState(false);
    const [scheduleDate, setScheduleDate] = useState("");
    const [instagramShareMode, setInstagramShareMode] = useState(socialPostSettings.instagramShareMode || 'CUSTOM');
    const [tiktokPostMode, setTiktokPostMode] = useState(socialPostSettings.tiktokPostMode || 'DIRECT_POST');
    const [tiktokIsAigc, setTiktokIsAigc] = useState(!!socialPostSettings.tiktokIsAigc);
    const [facebookPageId, setFacebookPageId] = useState(socialPostSettings.facebookPageId || '');
    const [pinterestBoardId, setPinterestBoardId] = useState(socialPostSettings.pinterestBoardId || '');

    const [posting, setPosting] = useState(false);
    const [postResult, setPostResult] = useState(null);
    const [isRefreshingPostStatus, setIsRefreshingPostStatus] = useState(false);
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
    const [editError, setEditError] = useState(null);
    const isBusy = isEditing || isSubtitling || isHooking || isTranslating || isTrimming || isPreviewRendering || isRenderingClip || isSelectingVersion;
    const clipDuration = Number.isFinite(Number(clip.display_duration))
        ? Number(clip.display_duration)
        : Math.max(0, (clip.end || 0) - (clip.start || 0));
    const displayPlatformResults = buildDisplayPlatformResults(postResult);

    // Initialize/Reset form when modal opens
    useEffect(() => {
        if (showModal) {
            const savedPostStatus = clip.social_post_status || null;
            setPostTitle(clip.video_title_for_youtube_short || "Viral Short");
            setPostDescription(clip.video_description_for_instagram || clip.video_description_for_tiktok || "");
            setFirstComment("");
            setIsScheduling(false);
            setScheduleDate("");
            setPlatforms({ ...DEFAULT_SOCIAL_POST_SETTINGS.platforms, ...(socialPostSettings.platforms || {}) });
            setInstagramShareMode(socialPostSettings.instagramShareMode || 'CUSTOM');
            setTiktokPostMode(socialPostSettings.tiktokPostMode || 'DIRECT_POST');
            setTiktokIsAigc(!!socialPostSettings.tiktokIsAigc);
            setFacebookPageId(socialPostSettings.facebookPageId || '');
            setPinterestBoardId(socialPostSettings.pinterestBoardId || '');
            setPostResult(savedPostStatus);
            if (savedPostStatus && (savedPostStatus.request_id || savedPostStatus.job_id)) {
                refreshPostStatus(savedPostStatus, { silent: true });
            }
        }
    }, [showModal, clip, socialPostSettings]);

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
            if (tracking.requested_platforms?.length) params.set('platforms', tracking.requested_platforms.join(','));
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

            if (showModal && (data.status === 'pending' || data.status === 'in_progress' || data.pending_count > 0)) {
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
                throw new Error("Gemini API Key is missing. Please set it in Settings.");
            }
            if (provider === 'ollama' && !resolvedOllamaModel) {
                throw new Error("Ollama model is missing. Please set it in Settings.");
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
                throw new Error("ElevenLabs API Key is missing. Please set it in Settings.");
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
        try {
            const res = await fetch(getApiUrl('/api/trim'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    input_filename: currentVideoUrl.split('/').pop(),
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
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsTrimming(false);
        }
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

    const handlePreviewRender = async () => {
        setIsPreviewRendering(true);
        setEditError(null);
        try {
            const res = await fetch(getApiUrl('/api/clip/preview/render'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: clipIndex,
                    apply_tight_edit: false,
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
            setIsPreviewRendering(false);
        }
    };

    const handlePost = async () => {
        if (!uploadPostKey || !uploadUserId) {
            setPostResult({ success: false, status: 'failed', message: "Missing API Key or User ID.", platform_results: [] });
            return;
        }

        const selectedPlatforms = Object.keys(platforms).filter(k => platforms[k]);
        if (selectedPlatforms.length === 0) {
            setPostResult({ success: false, status: 'failed', message: "Select at least one platform.", platform_results: [] });
            return;
        }

        if (!activeUploadProfile && !uploadUserId) {
            setPostResult({ success: false, status: 'failed', message: "No Upload-Post profile selected in Settings.", platform_results: [] });
            return;
        }

        if (selectedPlatforms.includes('pinterest') && !pinterestBoardId.trim()) {
            setPostResult({ success: false, status: 'failed', message: "Pinterest requires a board ID.", platform_results: [] });
            return;
        }

        if (isScheduling && !scheduleDate) {
            setPostResult({ success: false, status: 'failed', message: "Please select a date and time.", platform_results: [] });
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
                user_id: activeUploadProfile || uploadUserId,
                platforms: selectedPlatforms,
                title: postTitle,
                description: postDescription,
                first_comment: firstComment,
                instagram_share_mode: instagramShareMode,
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

            if (data.request_id || data.job_id) {
                postStatusTimeoutRef.current = window.setTimeout(() => {
                    refreshPostStatus(data, { silent: true });
                }, POST_STATUS_POLL_INTERVAL_MS);
            }

        } catch (e) {
            setPostResult({
                success: false,
                status: 'failed',
                message: `Failed: ${e.message}`,
                platform_results: [],
                requested_platforms: selectedPlatforms,
                scheduled: isScheduling,
            });
        } finally {
            setPosting(false);
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
        <div className="bg-surface border border-white/5 rounded-2xl overflow-hidden flex flex-col group hover:border-white/10 transition-all animate-[fadeIn_0.5s_ease-out] min-h-[300px] h-auto" style={{ animationDelay: `${index * 0.1}s` }}>
            {/* Top: Video Preview (Full Width) */}
            <div className="w-full bg-black/40 border-b border-white/5 p-3">
                <div className="mx-auto w-full max-w-[360px] aspect-[9/16] bg-black rounded-xl overflow-hidden relative group/video">
                <video
                    ref={videoRef}
                    src={currentVideoUrl}
                    controls
                    className="w-full h-full object-contain"
                    playsInline
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
                            Draft Preview
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
                        <span className="text-xs font-bold text-white uppercase tracking-wider">AI Magic in Progress...</span>
                        <span className="text-[10px] text-zinc-400 mt-1">Applying viral edits & zooms</span>
                    </div>
                )}
                </div>
            </div>

            {/* Bottom: Content & Details */}
            <div className="flex-1 p-4 md:p-5 flex flex-col bg-[#121214] overflow-y-auto md:overflow-hidden custom-scrollbar touch-scroll min-w-0">
                <div className="mb-4">
                    <h3 className="text-base font-bold text-white leading-tight line-clamp-2 mb-2 break-words" title={clip.video_title_for_youtube_short}>
                        {clip.video_title_for_youtube_short || "Viral Clip Generated"}
                    </h3>
                    <div className="flex flex-wrap gap-2 text-[10px] text-zinc-500 font-mono">
                        <span className="bg-white/5 px-1.5 py-0.5 rounded border border-white/5 shrink-0">{Math.round(clipDuration)}s</span>
                        <span className="bg-white/5 px-1.5 py-0.5 rounded border border-white/5 shrink-0">#shorts</span>
                        <span className="bg-white/5 px-1.5 py-0.5 rounded border border-white/5 shrink-0">#viral</span>
                    </div>
                </div>

                <div className="mb-4 p-3 bg-black/20 rounded-lg border border-white/5">
                    <div className="flex items-center justify-between gap-3 mb-2">
                        <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Version Chain</span>
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
                            {clipVersions[0]?.label || (isPreviewOnly ? 'Draft (not rendered yet)' : 'Original')}
                        </div>
                    )}
                </div>

                {/* Scrollable Descriptions Area */}
                <div className="flex-1 overflow-y-auto custom-scrollbar space-y-3 pr-2 mb-4">
                    {/* YouTube */}
                    <div className="bg-black/20 rounded-lg p-3 border border-white/5">
                        <div className="flex items-center gap-2 text-[10px] font-bold text-red-400 mb-1.5 uppercase tracking-wider">
                            <Youtube size={12} className="shrink-0" /> <span className="truncate">YouTube Title</span>
                        </div>
                        <p className="text-xs text-zinc-300 select-all break-words">
                            {clip.video_title_for_youtube_short || "Viral Short Video"}
                        </p>
                    </div>

                    {/* TikTok / IG */}
                    <div className="bg-black/20 rounded-lg p-3 border border-white/5">
                        <div className="flex items-center gap-2 text-[10px] font-bold text-zinc-400 mb-1.5 uppercase tracking-wider">
                            <Video size={12} className="text-cyan-400 shrink-0" />
                            <span className="text-zinc-500">/</span>
                            <Instagram size={12} className="text-pink-400 shrink-0" />
                            <span className="truncate">Caption</span>
                        </div>
                        <p className="text-xs text-zinc-300 line-clamp-3 hover:line-clamp-none transition-all cursor-pointer select-all break-words">
                            {clip.video_description_for_tiktok || clip.video_description_for_instagram}
                        </p>
                    </div>
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
                        Preview-Modus: Untertitel/Hook koennen als Stil gespeichert werden. <b>Preview Render</b> rendert absichtlich nur ein kurzes 1s-Sample (Turbo) fuer Positionierung, danach <b>Final Render</b>.
                    </div>
                )}
                <div className="grid grid-cols-2 gap-3 mt-auto pt-4 border-t border-white/5">
                    {isPreviewOnly && (
                        <button
                            onClick={handlePreviewRender}
                            disabled={isBusy}
                            className="col-span-2 py-2 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-emerald-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 mb-1 truncate px-1 disabled:opacity-60"
                        >
                            {isPreviewRendering ? <Loader2 size={14} className="animate-spin" /> : <Video size={14} />}
                            {isPreviewRendering ? 'Rendering Preview...' : 'Preview Render (1s Turbo)'}
                        </button>
                    )}
                    {isPreviewOnly && (
                        <button
                            onClick={handleRenderClip}
                            disabled={isBusy}
                            className="col-span-2 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-cyan-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 mb-1 truncate px-1 disabled:opacity-60"
                        >
                            {isRenderingClip ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                            {isRenderingClip ? 'Rendering...' : 'Final Render (Version erstellen)'}
                        </button>
                    )}
                    <button
                        onClick={handleAutoEdit}
                        disabled={isBusy || isPreviewOnly}
                        className="col-span-1 py-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-purple-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 mb-1 truncate px-1"
                    >
                        {isEditing ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                        {isEditing ? 'Editing...' : 'Auto Edit'}
                    </button>

                    <button
                        onClick={() => setShowSubtitleModal(true)}
                        disabled={isBusy}
                        className="col-span-1 py-2 bg-gradient-to-r from-yellow-600 to-orange-600 hover:from-yellow-500 hover:to-orange-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-orange-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 mb-1 truncate px-1"
                    >
                        {isSubtitling ? <Loader2 size={14} className="animate-spin" /> : <Type size={14} />}
                        {isSubtitling ? 'Adding...' : (isPreviewOnly ? 'Save Subtitle Style' : 'Subtitles')}
                    </button>

                    <button
                        onClick={() => setShowHookModal(true)}
                        disabled={isBusy}
                        className="col-span-1 py-2 bg-gradient-to-r from-amber-400 to-yellow-500 hover:from-amber-300 hover:to-yellow-400 text-black rounded-lg text-xs font-bold shadow-lg shadow-yellow-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 mb-1 truncate px-1"
                    >
                        {isHooking ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                        {isHooking ? 'Adding...' : (isPreviewOnly ? 'Save Hook Style' : 'Viral Hook')}
                    </button>

                    <button
                        onClick={() => setShowTrimModal(true)}
                        disabled={isBusy || isPreviewOnly}
                        className="col-span-1 py-2 bg-gradient-to-r from-blue-500 to-cyan-600 hover:from-blue-400 hover:to-cyan-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-cyan-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 mb-1 truncate px-1"
                    >
                        {isTrimming ? <Loader2 size={14} className="animate-spin" /> : <Scissors size={14} />}
                        {isTrimming ? 'Trimming...' : 'Trim'}
                    </button>

                    <button
                        onClick={() => setShowTranslateModal(true)}
                        disabled={isBusy || isPreviewOnly}
                        className="col-span-1 py-2 bg-gradient-to-r from-green-500 to-teal-600 hover:from-green-400 hover:to-teal-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-green-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 mb-1 truncate px-1"
                    >
                        {isTranslating ? <Loader2 size={14} className="animate-spin" /> : <Languages size={14} />}
                        {isTranslating ? 'Translating...' : 'Dub Voice'}
                    </button>

                    <button
                        onClick={() => setShowModal(true)}
                        disabled={isPreviewOnly}
                        className="col-span-1 py-2 bg-primary hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-xs font-bold shadow-lg shadow-primary/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 truncate px-2"
                    >
                        <Share2 size={14} className="shrink-0" /> Post
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
                        className="col-span-1 py-2 bg-white/5 hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed text-zinc-300 hover:text-white rounded-lg text-xs font-medium transition-colors flex items-center justify-center gap-2 border border-white/5 truncate px-2"
                    >
                        <Download size={14} className="shrink-0" /> Download
                    </button>

                    <button
                        onClick={restoreOriginalVersion}
                        disabled={!isModifiedVideo || isBusy || isPreviewOnly}
                        className="col-span-2 py-2 bg-black/30 hover:bg-black/50 disabled:opacity-40 disabled:cursor-not-allowed text-zinc-300 hover:text-white rounded-lg text-xs font-medium transition-colors flex items-center justify-center gap-2 border border-white/5 truncate px-2"
                    >
                        <RotateCcw size={14} className="shrink-0" /> Original wiederherstellen
                    </button>
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

                        <h3 className="text-lg font-bold text-white mb-4">Post / Schedule</h3>

                        <div className="mb-4 rounded-lg border border-white/5 bg-white/5 px-3 py-2 text-xs text-zinc-400">
                            Active profile: <span className="text-white font-medium">{activeUploadProfile || uploadUserId || 'No profile selected'}</span>
                        </div>

                        {!uploadPostKey && (
                            <div className="mb-4 p-3 bg-yellow-500/10 border border-yellow-500/20 text-yellow-200 text-xs rounded-lg flex items-start gap-2">
                                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                                <div>Configure API Key in Settings first.</div>
                            </div>
                        )}

                        <div className="space-y-4 mb-6">
                            {/* Title & Description */}
                            <div>
                                <label className="block text-xs font-bold text-zinc-400 mb-1">Video Title</label>
                                <input
                                    type="text"
                                    value={postTitle}
                                    onChange={(e) => setPostTitle(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50 placeholder-zinc-600"
                                    placeholder="Enter a catchy title..."
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-bold text-zinc-400 mb-1">Caption / Description</label>
                                <textarea
                                    value={postDescription}
                                    onChange={(e) => setPostDescription(e.target.value)}
                                    rows={4}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50 placeholder-zinc-600 resize-none"
                                    placeholder="Write a caption for your post..."
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-bold text-zinc-400 mb-1">First Comment (optional)</label>
                                <textarea
                                    value={firstComment}
                                    onChange={(e) => setFirstComment(e.target.value)}
                                    rows={3}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50 placeholder-zinc-600 resize-none"
                                    placeholder="Will be sent where Upload-Post supports first comments."
                                />
                            </div>

                            {/* Scheduling */}
                            <div className="p-3 bg-white/5 rounded-lg border border-white/5">
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-2 text-sm text-white font-medium">
                                        <Calendar size={16} className="text-purple-400" /> Schedule Post
                                    </div>
                                    <label className="relative inline-flex items-center cursor-pointer">
                                        <input type="checkbox" checked={isScheduling} onChange={(e) => setIsScheduling(e.target.checked)} className="sr-only peer" />
                                        <div className="w-9 h-5 bg-zinc-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-600"></div>
                                    </label>
                                </div>

                                {isScheduling && (
                                    <div className="mt-3 animate-[fadeIn_0.2s_ease-out]">
                                        <label className="block text-xs text-zinc-400 mb-1">Select Date & Time</label>
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
                                <label className="block text-xs font-bold text-zinc-400 mb-2">Select Platforms</label>
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
                                    <label className="block text-xs font-bold text-zinc-400 mb-2">Instagram Share Mode</label>
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
                                    <p className="mt-2 text-[11px] text-zinc-600 leading-relaxed">
                                        Upload-Post uses the embedded original audio. The shared text for Instagram is sent via the Reel title field, not the global description field.
                                    </p>
                                </div>
                            )}

                            {platforms.tiktok && (
                                <div className="p-3 bg-white/5 rounded-lg border border-white/5 space-y-3">
                                    <div>
                                        <label className="block text-xs font-bold text-zinc-400 mb-2">TikTok Post Mode</label>
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
                                        Mark this TikTok upload as AI-generated
                                    </label>
                                </div>
                            )}

                            {platforms.facebook && (
                                <div className="p-3 bg-white/5 rounded-lg border border-white/5">
                                    <label className="block text-xs font-bold text-zinc-400 mb-2">Facebook Page ID</label>
                                    <input
                                        type="text"
                                        value={facebookPageId}
                                        onChange={(e) => setFacebookPageId(e.target.value)}
                                        className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                        placeholder="Optional if only one page is connected"
                                    />
                                </div>
                            )}

                            {platforms.pinterest && (
                                <div className="p-3 bg-white/5 rounded-lg border border-white/5">
                                    <label className="block text-xs font-bold text-zinc-400 mb-2">Pinterest Board ID</label>
                                    <input
                                        type="text"
                                        value={pinterestBoardId}
                                        onChange={(e) => setPinterestBoardId(e.target.value)}
                                        className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-primary/50"
                                        placeholder="Required by Upload-Post for Pinterest"
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
                                            Status: <span className="uppercase tracking-wide">{postResult.status || 'unknown'}</span>
                                            {' · '}
                                            Success {postResult.success_count || 0}
                                            {' · '}
                                            Failed {postResult.failure_count || 0}
                                            {' · '}
                                            Pending {postResult.pending_count || 0}
                                        </div>
                                        {(postResult.request_id || postResult.job_id) && (
                                            <div className="mt-1 text-[10px] text-zinc-400 break-all">
                                                {postResult.request_id ? `Request ID: ${postResult.request_id}` : null}
                                                {postResult.request_id && postResult.job_id ? ' · ' : null}
                                                {postResult.job_id ? `Vendor Job ID: ${postResult.job_id}` : null}
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
                                                                {isNotSelected ? 'not_selected' : (item.status || (isPending ? 'pending' : item.success ? 'success' : 'failed'))}
                                                            </span>
                                                        </div>
                                                    </div>
                                                    <div className="mt-1 text-[11px] text-zinc-300">
                                                        {item.message || item.error || (isPending ? 'Warte auf Rueckmeldung von Upload-Post.' : (isNotSelected ? 'Nicht ausgewaehlt.' : 'Completed'))}
                                                    </div>
                                                    {(item.url || item.link) && (
                                                        <a
                                                            href={item.url || item.link}
                                                            target="_blank"
                                                            rel="noreferrer"
                                                            className="mt-2 inline-flex text-[11px] text-cyan-300 hover:text-cyan-200"
                                                        >
                                                            Open post
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
                                            Refresh Status
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

                        <button
                            onClick={handlePost}
                            disabled={posting || !uploadPostKey}
                            className="w-full py-3 bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-white font-bold transition-all flex items-center justify-center gap-2"
                        >
                            {posting ? <><Loader2 size={16} className="animate-spin" /> {isScheduling ? 'Scheduling...' : 'Publishing...'}</> : <><Share2 size={16} /> {isScheduling ? 'Schedule Post' : 'Publish Now'}</>}
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
                isProcessing={isSubtitling}
                videoUrl={currentVideoUrl}
                defaultSettings={subtitleStyle}
            />

            <HookModal
                isOpen={showHookModal}
                onClose={() => setShowHookModal(false)}
                onGenerate={handleHook}
                isProcessing={isHooking}
                videoUrl={currentVideoUrl}
                initialText={clip.viral_hook_text}
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
                onClose={() => setShowTrimModal(false)}
                onTrim={handleTrim}
                isProcessing={isTrimming}
                videoUrl={currentVideoUrl}
            />
        </div>
    );
}
