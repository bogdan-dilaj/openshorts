import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock, Loader2, Share2, Upload } from 'lucide-react';
import { getApiUrl } from '../config';
import { DEFAULT_SOCIAL_POST_SETTINGS, INSTAGRAM_SHARE_MODES, SOCIAL_PLATFORM_OPTIONS, TIKTOK_POST_MODES } from '../socialOptions';

const POST_STATUS_POLL_INTERVAL_MS = 4000;
const PLATFORM_LABELS = SOCIAL_PLATFORM_OPTIONS.reduce((acc, item) => {
  acc[item.key] = item.label;
  return acc;
}, {});

const normalizePlatformKey = (value) => {
  const normalized = (value || '').toString().trim().toLowerCase();
  if (!normalized) return '';
  if (normalized === 'twitter') return 'x';
  if (normalized === 'yt') return 'youtube';
  if (normalized === 'ig') return 'instagram';
  if (normalized === 'fb') return 'facebook';
  return normalized;
};

const getPlatformLabel = (value) => PLATFORM_LABELS[value] || value;

const buildDisplayPlatformResults = (result) => {
  if (!result) return [];

  const requested = (result.requested_platforms || [])
    .map(normalizePlatformKey)
    .filter(Boolean);
  const resultRows = (result.platform_results || [])
    .map((item) => ({
      ...item,
      platform: normalizePlatformKey(item.platform),
    }))
    .filter((item) => item.platform);

  if (!requested.length && !resultRows.length) return [];

  const byPlatform = new Map();
  for (const item of resultRows) {
    byPlatform.set(item.platform, item);
  }

  const requestedSet = new Set(requested);
  return SOCIAL_PLATFORM_OPTIONS.map((option) => {
    const key = option.key;
    if (byPlatform.has(key)) return byPlatform.get(key);
    if (requestedSet.has(key)) {
      return {
        platform: key,
        success: null,
        status: 'pending',
        message: 'Warte auf Rückmeldung von Upload-Post.',
      };
    }
    return {
      platform: key,
      success: null,
      status: 'not_selected',
      message: 'Nicht für diesen Post ausgewählt.',
    };
  });
};

const readErrorText = async (res) => {
  const errText = await res.text();
  try {
    const jsonErr = JSON.parse(errText);
    return jsonErr.detail || errText;
  } catch (e) {
    return errText;
  }
};

export default function SocialUploadStudio({
  uploadPostKey,
  uploadUserId,
  socialPostSettings = DEFAULT_SOCIAL_POST_SETTINGS,
}) {
  const [videoFile, setVideoFile] = useState(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [firstComment, setFirstComment] = useState('');
  const [platforms, setPlatforms] = useState({ ...DEFAULT_SOCIAL_POST_SETTINGS.platforms, ...(socialPostSettings.platforms || {}) });
  const [instagramShareMode, setInstagramShareMode] = useState(socialPostSettings.instagramShareMode || 'CUSTOM');
  const [tiktokPostMode, setTiktokPostMode] = useState(socialPostSettings.tiktokPostMode || 'DIRECT_POST');
  const [tiktokIsAigc, setTiktokIsAigc] = useState(!!socialPostSettings.tiktokIsAigc);
  const [facebookPageId, setFacebookPageId] = useState(socialPostSettings.facebookPageId || '');
  const [pinterestBoardId, setPinterestBoardId] = useState(socialPostSettings.pinterestBoardId || '');
  const [posting, setPosting] = useState(false);
  const [postResult, setPostResult] = useState(null);
  const [isRefreshingPostStatus, setIsRefreshingPostStatus] = useState(false);
  const postStatusTimeoutRef = useRef(null);

  useEffect(() => {
    setPlatforms({ ...DEFAULT_SOCIAL_POST_SETTINGS.platforms, ...(socialPostSettings.platforms || {}) });
    setInstagramShareMode(socialPostSettings.instagramShareMode || 'CUSTOM');
    setTiktokPostMode(socialPostSettings.tiktokPostMode || 'DIRECT_POST');
    setTiktokIsAigc(!!socialPostSettings.tiktokIsAigc);
    setFacebookPageId(socialPostSettings.facebookPageId || '');
    setPinterestBoardId(socialPostSettings.pinterestBoardId || '');
  }, [socialPostSettings]);

  useEffect(() => () => {
    if (postStatusTimeoutRef.current) {
      clearTimeout(postStatusTimeoutRef.current);
    }
  }, []);

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

      if ((data.status === 'pending' || data.status === 'in_progress') && (data.request_id || data.job_id)) {
        postStatusTimeoutRef.current = window.setTimeout(() => {
          refreshPostStatus(data, { silent: true });
        }, POST_STATUS_POLL_INTERVAL_MS);
      } else {
        stopPostStatusPolling();
      }
    } catch (error) {
      setPostResult((prev) => prev ? {
        ...prev,
        poll_error: error.message || 'Status-Aktualisierung fehlgeschlagen.',
      } : prev);
      stopPostStatusPolling();
    } finally {
      if (!silent) {
        setIsRefreshingPostStatus(false);
      }
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    stopPostStatusPolling();

    const selectedPlatforms = Object.keys(platforms).filter((key) => platforms[key]);
    if (!uploadPostKey || !uploadUserId) {
      setPostResult({ success: false, status: 'failed', message: 'Upload-Post API-Key oder Profil fehlt.', platform_results: [] });
      return;
    }
    if (!videoFile) {
      setPostResult({ success: false, status: 'failed', message: 'Bitte eine Videodatei auswählen.', platform_results: [] });
      return;
    }
    if (!title.trim()) {
      setPostResult({ success: false, status: 'failed', message: 'Bitte einen Titel eingeben.', platform_results: [] });
      return;
    }
    if (!selectedPlatforms.length) {
      setPostResult({ success: false, status: 'failed', message: 'Mindestens eine Plattform auswählen.', platform_results: [] });
      return;
    }
    if (selectedPlatforms.includes('pinterest') && !pinterestBoardId.trim()) {
      setPostResult({ success: false, status: 'failed', message: 'Pinterest benötigt eine Board-ID.', platform_results: [] });
      return;
    }

    const formData = new FormData();
    formData.append('video', videoFile);
    formData.append('api_key', uploadPostKey);
    formData.append('user_id', uploadUserId);
    formData.append('platforms', JSON.stringify(selectedPlatforms));
    formData.append('title', title.trim());
    formData.append('description', description.trim());
    formData.append('first_comment', firstComment.trim());
    formData.append('instagram_share_mode', instagramShareMode);
    formData.append('tiktok_post_mode', tiktokPostMode);
    formData.append('tiktok_is_aigc', tiktokIsAigc ? 'true' : 'false');
    if (facebookPageId.trim()) formData.append('facebook_page_id', facebookPageId.trim());
    if (pinterestBoardId.trim()) formData.append('pinterest_board_id', pinterestBoardId.trim());

    setPosting(true);
    setPostResult(null);
    try {
      const res = await fetch(getApiUrl('/api/social/post/upload'), {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        throw new Error(await readErrorText(res));
      }

      const data = await res.json();
      setPostResult(data);
      if (data.request_id || data.job_id) {
        postStatusTimeoutRef.current = window.setTimeout(() => {
          refreshPostStatus(data, { silent: true });
        }, POST_STATUS_POLL_INTERVAL_MS);
      }
    } catch (error) {
      setPostResult({
        success: false,
        status: 'failed',
        message: `Fehlgeschlagen: ${error.message}`,
        platform_results: [],
        requested_platforms: selectedPlatforms,
      });
    } finally {
      setPosting(false);
    }
  };

  const displayPlatformResults = buildDisplayPlatformResults(postResult);

  return (
    <div className="h-full overflow-y-auto touch-scroll p-5 md:p-8 max-w-4xl mx-auto animate-[fadeIn_0.3s_ease-out]">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Upload-Post Direkt-Upload</h1>
        <p className="text-sm text-zinc-400 mt-1">
          Video hochladen, Titel/Beschreibung ausfüllen und direkt veröffentlichen, ohne Clip in OpenShorts zu speichern.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="glass-panel p-5 space-y-4">
          <div className="text-xs text-zinc-400">
            Aktives Profil: <span className="text-white font-medium">{uploadUserId || 'Kein Profil ausgewählt'}</span>
          </div>

          {!uploadPostKey && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
              Upload-Post API-Key fehlt. Bitte zuerst in den Einstellungen setzen.
            </div>
          )}

          <div>
            <label className="block text-xs font-bold text-zinc-400 mb-2">Videodatei</label>
            <label className="w-full flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-300 cursor-pointer hover:bg-white/10 transition-colors">
              <Upload size={16} className="text-primary" />
              <span className="truncate">{videoFile?.name || 'Videodatei wählen'}</span>
              <input
                type="file"
                accept="video/*"
                className="hidden"
                onChange={(e) => setVideoFile(e.target.files?.[0] || null)}
              />
            </label>
          </div>

          <div>
            <label className="block text-xs font-bold text-zinc-400 mb-2">Titel</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-primary/40"
              placeholder="Post-Titel"
              maxLength={220}
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-zinc-400 mb-2">Beschreibung</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full h-24 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-primary/40"
              placeholder="Post-Beschreibung / Caption"
              maxLength={2200}
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-zinc-400 mb-2">Erster Kommentar (optional)</label>
            <textarea
              value={firstComment}
              onChange={(e) => setFirstComment(e.target.value)}
              className="w-full h-20 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-primary/40"
              placeholder="Wird gesendet, wo Upload-Post erste Kommentare unterstützt."
              maxLength={500}
            />
          </div>
        </div>

        <div className="glass-panel p-5 space-y-4">
          <label className="block text-xs font-bold text-zinc-400">Plattformen auswählen</label>
          <div className="grid sm:grid-cols-2 gap-2">
            {SOCIAL_PLATFORM_OPTIONS.map((platform) => (
              <label key={platform.key} className="flex items-center gap-3 p-3 bg-white/5 rounded-lg cursor-pointer hover:bg-white/10 transition-colors border border-white/5">
                <input
                  type="checkbox"
                  checked={!!platforms[platform.key]}
                  onChange={(e) => setPlatforms({ ...platforms, [platform.key]: e.target.checked })}
                  className="accent-primary w-4 h-4"
                />
                <span className="text-sm text-zinc-200">{platform.label}</span>
              </label>
            ))}
          </div>

          {platforms.instagram && (
            <div>
              <label className="block text-xs font-bold text-zinc-400 mb-2">Instagram-Share-Mode</label>
              <select
                value={instagramShareMode}
                onChange={(e) => setInstagramShareMode(e.target.value)}
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-200"
              >
                {INSTAGRAM_SHARE_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value} className="bg-zinc-900">{mode.label}</option>
                ))}
              </select>
            </div>
          )}

          {platforms.tiktok && (
            <>
              <div>
                <label className="block text-xs font-bold text-zinc-400 mb-2">TikTok-Post-Mode</label>
                <select
                  value={tiktokPostMode}
                  onChange={(e) => setTiktokPostMode(e.target.value)}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-200"
                >
                  {TIKTOK_POST_MODES.map((mode) => (
                    <option key={mode.value} value={mode.value} className="bg-zinc-900">{mode.label}</option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-3 text-sm text-zinc-200">
                <input
                  type="checkbox"
                  checked={tiktokIsAigc}
                  onChange={(e) => setTiktokIsAigc(e.target.checked)}
                  className="accent-primary w-4 h-4"
                />
                Als KI-generierten Inhalt markieren
              </label>
            </>
          )}

          {platforms.facebook && (
            <div>
              <label className="block text-xs font-bold text-zinc-400 mb-2">Facebook-Page-ID (optional)</label>
              <input
                value={facebookPageId}
                onChange={(e) => setFacebookPageId(e.target.value)}
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
                placeholder="Page-ID für Facebook-Reels"
              />
            </div>
          )}

          {platforms.pinterest && (
            <div>
              <label className="block text-xs font-bold text-zinc-400 mb-2">Pinterest-Board-ID</label>
              <input
                value={pinterestBoardId}
                onChange={(e) => setPinterestBoardId(e.target.value)}
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
                placeholder="Für Pinterest von Upload-Post erforderlich"
              />
            </div>
          )}
        </div>

        {postResult && (
          <div className={`glass-panel p-4 border ${postResult.failure_count ? 'border-red-500/30' : postResult.success === false ? 'border-red-500/30' : postResult.pending_count ? 'border-amber-500/30' : 'border-emerald-500/30'}`}>
            <div className="flex items-start gap-2">
              {postResult.failure_count ? (
                <AlertCircle size={18} className="text-red-400 mt-0.5" />
              ) : postResult.success === false ? (
                <AlertCircle size={18} className="text-red-400 mt-0.5" />
              ) : postResult.pending_count ? (
                <Clock size={18} className="text-amber-300 mt-0.5" />
              ) : (
                <CheckCircle2 size={18} className="text-emerald-400 mt-0.5" />
              )}
              <div className="text-sm">
                <div className="font-semibold text-white">{postResult.message}</div>
                <div className="text-xs text-zinc-400 mt-1">
                  Status: <span className="uppercase tracking-wide">{postResult.status || 'unbekannt'}</span> · Erfolgreich {postResult.success_count || 0} · Fehlgeschlagen {postResult.failure_count || 0} · Offen {postResult.pending_count || 0}
                </div>
                {(postResult.request_id || postResult.job_id) && (
                  <div className="text-[10px] text-zinc-500 mt-1">
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
                  const isSuccess = item.success === true;
                  const isFailure = item.success === false;
                  const isNotSelected = item.status === 'not_selected';
                  const isPending = !isNotSelected && !isSuccess && !isFailure;
                  const rowClass = isSuccess
                    ? 'border-emerald-500/40 bg-emerald-500/10'
                    : isFailure
                      ? 'border-red-500/40 bg-red-500/10'
                      : isNotSelected
                        ? 'border-white/10 bg-white/5'
                        : 'border-amber-500/40 bg-amber-500/10';
                  return (
                    <div key={`${item.platform}-${item.publish_id || item.post_id || item.message || 'pending'}`} className={`rounded-lg border px-3 py-2 ${rowClass}`}>
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-xs font-semibold text-white">{getPlatformLabel(item.platform)}</div>
                        <div className="text-[10px] uppercase tracking-wide text-zinc-300">
                          {isSuccess ? 'erfolgreich' : isFailure ? 'fehlgeschlagen' : isNotSelected ? 'nicht ausgewählt' : (item.status || 'offen')}
                        </div>
                      </div>
                      <div className="mt-1 text-[11px] text-zinc-200">
                        {item.message || item.error || (isPending ? 'Warte auf Rückmeldung von Upload-Post.' : (isNotSelected ? 'Nicht ausgewählt.' : 'Abgeschlossen'))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {(postResult.request_id || postResult.job_id) && (
              <button
                type="button"
                onClick={() => refreshPostStatus(postResult)}
                disabled={isRefreshingPostStatus}
                className="mt-3 inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-200 hover:bg-white/10 disabled:opacity-60"
              >
                {isRefreshingPostStatus ? <Loader2 size={12} className="animate-spin" /> : <Clock size={12} />}
                Status aktualisieren
              </button>
            )}
          </div>
        )}

        <div className="flex items-center justify-end gap-3">
          <button
            type="submit"
            disabled={posting || !uploadPostKey || !uploadUserId}
            className="px-4 py-2 rounded-lg bg-primary text-black font-bold text-sm hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {posting ? <><Loader2 size={16} className="animate-spin" /> Veröffentliche...</> : <><Share2 size={16} /> Über Upload-Post veröffentlichen</>}
          </button>
        </div>
      </form>
    </div>
  );
}
