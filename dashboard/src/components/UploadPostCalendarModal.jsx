import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Cloud, HardDrive, Loader2, RefreshCcw, Save, Trash2, X } from 'lucide-react';
import { getApiUrl } from '../config';
import { INSTAGRAM_SHARE_MODES, SOCIAL_PLATFORM_OPTIONS, TIKTOK_POST_MODES } from '../socialOptions';

const VIEW_MODES = [
  { key: 'month', label: 'Monat' },
  { key: 'week', label: 'Woche' },
  { key: 'day', label: 'Tag' },
];

const STATUS_STYLES = {
  upcoming: 'border-zinc-500/25 bg-zinc-500/12 text-zinc-100',
  scheduled: 'border-cyan-500/30 bg-cyan-500/15 text-cyan-100',
  posted: 'border-emerald-500/30 bg-emerald-500/15 text-emerald-100',
  failed: 'border-red-500/40 bg-red-500/20 text-red-100',
  partial: 'border-amber-500/40 bg-amber-500/20 text-amber-100',
  deleted: 'border-zinc-500/20 bg-zinc-500/10 text-zinc-400',
  unknown: 'border-white/10 bg-white/5 text-zinc-200',
  ready: 'border-white/10 bg-white/5 text-zinc-200',
  assigned: 'border-amber-400/40 bg-amber-400/18 text-amber-100',
};

const PLATFORM_LABELS = SOCIAL_PLATFORM_OPTIONS.reduce((acc, item) => {
  acc[item.key] = item.label;
  return acc;
}, {});

const normalizePlatformKey = (value) => {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'twitter') return 'x';
  return normalized;
};

const formatMonthLabel = (date) => new Intl.DateTimeFormat('de-DE', {
  month: 'long',
  year: 'numeric',
}).format(date);

const formatDayHeader = (date) => new Intl.DateTimeFormat('de-DE', {
  weekday: 'short',
  day: '2-digit',
  month: '2-digit',
}).format(date);

const formatTimeLabel = (value) => {
  if (!value) return '--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--:--';
  return new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit' }).format(date);
};

const formatDateTimeInputValue = (value) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (number) => String(number).padStart(2, '0');
  const year = date.getFullYear();
  const month = pad(date.getMonth() + 1);
  const day = pad(date.getDate());
  const hours = pad(date.getHours());
  const minutes = pad(date.getMinutes());
  return `${year}-${month}-${day}T${hours}:${minutes}`;
};

const parseDateInputToIso = (value) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toISOString();
};

const startOfDay = (date) => {
  const next = new Date(date);
  next.setHours(0, 0, 0, 0);
  return next;
};

const addDays = (date, amount) => {
  const next = new Date(date);
  next.setDate(next.getDate() + amount);
  return next;
};

const addMinutes = (date, amount) => {
  const next = new Date(date);
  next.setMinutes(next.getMinutes() + amount);
  return next;
};

const startOfWeek = (date) => {
  const next = startOfDay(date);
  const day = next.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  next.setDate(next.getDate() + diff);
  return next;
};

const isSameDay = (left, right) => (
  left.getFullYear() === right.getFullYear()
  && left.getMonth() === right.getMonth()
  && left.getDate() === right.getDate()
);

const buildMonthGrid = (cursorDate) => {
  const monthStart = new Date(cursorDate.getFullYear(), cursorDate.getMonth(), 1);
  const gridStart = startOfWeek(monthStart);
  return Array.from({ length: 42 }, (_, index) => addDays(gridStart, index));
};

const buildWeekDays = (cursorDate) => {
  const weekStart = startOfWeek(cursorDate);
  return Array.from({ length: 7 }, (_, index) => addDays(weekStart, index));
};

const buildDayQuarterHourSlots = (cursorDate) => {
  const dayStart = startOfDay(cursorDate);
  return Array.from({ length: 96 }, (_, index) => addMinutes(dayStart, index * 15));
};

const resolveStatusStyle = (status) => STATUS_STYLES[status] || STATUS_STYLES.unknown;

const resolveVideoUrl = (value) => {
  if (!value) return '';
  return value.startsWith('http://') || value.startsWith('https://') ? value : getApiUrl(value);
};

const resolveEntryPreviewUrl = (entry) => (
  resolveVideoUrl(entry?.local_video_url)
  || resolveVideoUrl(entry?.local_preview_video_url)
  || resolveVideoUrl(entry?.remote_preview_url)
  || ''
);

const resolveEntryMediaBadge = (entry) => {
  const hasLocalMedia = !!(
    entry?.has_local_media
    || entry?.media_origin === 'local'
    || (entry?.local_video_url && !String(entry.local_video_url).startsWith('http'))
    || (entry?.local_preview_video_url && !String(entry.local_preview_video_url).startsWith('http'))
  );
  if (hasLocalMedia) {
    return {
      icon: HardDrive,
      label: 'Lokal vorhanden',
      shortLabel: 'Lokal',
      className: 'text-emerald-200',
    };
  }
  return {
    icon: Cloud,
    label: 'Nur bei Upload-Post',
    shortLabel: 'Upload-Post',
    className: 'text-cyan-200',
  };
};

const floorToQuarterHour = (value) => {
  const date = value instanceof Date ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  date.setSeconds(0, 0);
  date.setMinutes(Math.floor(date.getMinutes() / 15) * 15);
  return date;
};

const buildDraftAssignmentDate = (dayDate, existingIso = '') => {
  const next = new Date(dayDate);
  const existing = existingIso ? new Date(existingIso) : null;
  if (existing && !Number.isNaN(existing.getTime())) {
    next.setHours(existing.getHours(), existing.getMinutes(), 0, 0);
  } else {
    next.setHours(12, 0, 0, 0);
  }
  const floored = floorToQuarterHour(next) || next;
  return floored.toISOString();
};

// --- Auto-Schedule helpers -------------------------------------------------

const AUTO_SCHEDULE_MIN_LEAD_MINUTES = 30;

// Liefert den Berlin-Offset (in Minuten) für ein gegebenes UTC-Datum.
// Berücksichtigt automatisch Sommer-/Winterzeit (CET = +01:00, CEST = +02:00).
const getTimezoneOffsetMinutes = (date, timeZone) => {
  try {
    const dtf = new Intl.DateTimeFormat('en-US', {
      timeZone,
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    const parts = dtf.formatToParts(date);
    const get = (type) => Number(parts.find((p) => p.type === type)?.value || 0);
    const asUtc = Date.UTC(
      get('year'),
      get('month') - 1,
      get('day'),
      get('hour'),
      get('minute'),
      get('second'),
    );
    return Math.round((asUtc - date.getTime()) / 60000);
  } catch (error) {
    return 0;
  }
};

const formatIsoWithTimezone = (date, timeZone) => {
  // Wand-Uhrzeit-Komponenten in der Ziel-Timezone ablesen — NICHT die UTC-
  // Felder des Date-Objekts, sonst entsteht ein widerspruechlicher String
  // (z. B. "11:00:00+01:00" statt korrekt "12:00:00+01:00").
  const offsetMinutes = getTimezoneOffsetMinutes(date, timeZone);
  const sign = offsetMinutes >= 0 ? '+' : '-';
  const abs = Math.abs(offsetMinutes);
  const hh = String(Math.floor(abs / 60)).padStart(2, '0');
  const mm = String(abs % 60).padStart(2, '0');
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  const parts = dtf.formatToParts(date);
  const get = (type) => Number(parts.find((p) => p.type === type)?.value || 0);
  // Intl kann hour=24 liefern, wenn hour12=false auf Mitternacht trifft.
  const hour = get('hour') % 24;
  const pad = (n) => String(n).padStart(2, '0');
  return (
    `${get('year')}-${pad(get('month'))}-${pad(get('day'))}` +
    `T${pad(hour)}:${pad(get('minute'))}:${pad(get('second'))}` +
    `${sign}${hh}:${mm}`
  );
};

// Wandelt einen "lokalen" Datums-/Zeitpunkt in der angegebenen Timezone
// in einen ISO-String mit korrektem UTC-Offset um. Wir konstruieren den
// Zielpunkt so, dass er in der Ziel-Timezone genau (year, month, day, h, m) hat.
const zonedTimeToIso = (year, month, day, hours, minutes, timeZone) => {
  // Wir suchen den UTC-Zeitpunkt, dessen Darstellung in `timeZone` exakt
  // (year, month, day, hours, minutes) entspricht. Initial nehmen wir an, dass
  // der Zielpunkt genau so in UTC liegt, und subtrahieren dann den aktuellen
  // Offset der Ziel-Timezone. Zwei Iterationen reichen, da der Offset sich
  // innerhalb derselben DST-Periode nicht aendert.
  const targetUtc = Date.UTC(year, month - 1, day, hours, minutes, 0);
  let offset = getTimezoneOffsetMinutes(new Date(targetUtc), timeZone);
  let utc = targetUtc - offset * 60000;
  for (let i = 0; i < 2; i += 1) {
    const nextOffset = getTimezoneOffsetMinutes(new Date(utc), timeZone);
    if (nextOffset === offset) break;
    offset = nextOffset;
    utc = targetUtc - offset * 60000;
  }
  return formatIsoWithTimezone(new Date(utc), timeZone);
};

// YYYY-MM-DD in der Ziel-Timezone für ein gegebenes JS-Date.
const formatYmdInTimezone = (date, timeZone) => {
  const dtf = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
  return dtf.format(date);
};

// HH:MM in der Ziel-Timezone.
const formatHmInTimezone = (date, timeZone) => {
  const dtf = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  return dtf.format(date);
};

// Parst eine mit ";" ODER "," getrennte Slotliste (z. B. "06:00; 12:00; 17:00; 21:00").
// Liefert sortierte unique Slots, gibt im Fehlerfall einen Fehlertext zurück.
const parseAutoScheduleSlots = (rawValue) => {
  const entries = String(rawValue || '')
    .split(/[;,\n\r]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!entries.length) {
    throw new Error('Mindestens einen Slot angeben, z. B. 06:00, 12:00, 17:00, 21:00.');
  }
  const seen = new Set();
  const slots = [];
  for (const entry of entries) {
    const match = entry.match(/^(\d{1,2})(?::(\d{1,2}))?$/);
    if (!match) {
      throw new Error(`Ungueltiger Slot "${entry}". Erlaubt ist HH:MM.`);
    }
    const hours = Number(match[1]);
    const minutes = Number(match[2] || '0');
    if (
      !Number.isInteger(hours) || hours < 0 || hours > 23 ||
      !Number.isInteger(minutes) || minutes < 0 || minutes > 59
    ) {
      throw new Error(`Ungueltiger Slot "${entry}". Stunden 0-23, Minuten 0-59.`);
    }
    const label = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
    if (seen.has(label)) continue;
    seen.add(label);
    slots.push({ hours, minutes, label });
  }
  slots.sort((a, b) => (a.hours * 60 + a.minutes) - (b.hours * 60 + b.minutes));
  return slots;
};

// Hash-basiertes, deterministisches "buntes Wuerfeln" ueber alle Jobs hinweg.
// Liefert eine Reihenfolge, in der aufeinanderfolgende Items moeglichst oft
// den Job wechseln, damit das Tagesprogramm abwechslungsreich wirkt.
const buildRoundRobinJobOrder = (items) => {
  const buckets = new Map();
  for (const item of items) {
    const key = item.job_id || 'unknown';
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(item);
  }
  // Innerhalb jedes Jobs mischen (deterministisch via item.id Hash).
  const hashSeed = (id) => {
    let h = 0;
    for (let i = 0; i < id.length; i += 1) {
      h = (h * 31 + id.charCodeAt(i)) >>> 0;
    }
    return h;
  };
  for (const [key, list] of buckets.entries()) {
    list.sort((a, b) => hashSeed(a.id) - hashSeed(b.id));
  }
  // Bucket-Reihenfolge ebenfalls per Hash mischen, damit der "erste" Clip
  // nicht immer aus dem gleichen Job kommt.
  const bucketKeys = Array.from(buckets.keys());
  bucketKeys.sort((a, b) => hashSeed(`__job__${a}`) - hashSeed(`__job__${b}`));
  const order = [];
  let added = true;
  while (added) {
    added = false;
    for (const key of bucketKeys) {
      const list = buckets.get(key);
      const next = list.shift();
      if (next) {
        order.push(next);
        added = true;
      }
    }
  }
  return order;
};

const normalizeIsoKey = (value) => {
  if (!value) return '';
  try {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toISOString();
  } catch (error) {
    return '';
  }
};

const buildAutoScheduleAssignments = ({
  items,
  slots,
  timeZone,
  minJobIntervalDays,
  maxPerJobPerDay,
  startFromDate,
  now = new Date(),
  existingDates = [],
  skipDates = [],
}) => {
  if (!Array.isArray(items) || !items.length) {
    return { assignments: {}, scheduledCount: 0, unscheduled: [], usedDates: [], skipped: 0 };
  }
  if (!Array.isArray(slots) || !slots.length) {
    throw new Error('Bitte mindestens einen Slot angeben.');
  }
  const minInterval = Math.max(1, Math.floor(Number(minJobIntervalDays) || 1));
  const maxPerDay = Math.max(1, Math.floor(Number(maxPerJobPerDay) || 1));
  const earliestAllowedTime = addMinutes(now, AUTO_SCHEDULE_MIN_LEAD_MINUTES).getTime();

  // Belegte Slots: vorhandene Kalender-Events + manuell reservierte Drafts +
  // explizit zu ueberspringende Daten (z. B. Slots, die der User fuer einen
  // anderen Clip in dieser Runde schon vergeben hat). Wir vergleichen auf
  // Sekundengranularitaet, damit 17:00:00 != 17:00:30 kollidieren.
  const occupied = new Set();
  for (const value of [...(existingDates || []), ...(skipDates || [])]) {
    const key = normalizeIsoKey(value);
    if (key) occupied.add(key);
  }

  // Startdatum (in der Ziel-Timezone) — standardmaessig "heute" in der TZ.
  let startYmd;
  if (startFromDate) {
    startYmd = formatYmdInTimezone(new Date(startFromDate), timeZone);
  } else {
    startYmd = formatYmdInTimezone(now, timeZone);
  }
  const [sy, sm, sd] = startYmd.split('-').map(Number);

  const ordered = buildRoundRobinJobOrder(items);

  // Slot-Grid: wir erzeugen einen Strom von (dateIndex, slotIndex) und vergeben
  // reihum. Pro Tag halten wir fest, wie viele Slots pro job_id schon vergeben
  // wurden; pro Job den letzten Tag, an dem ein Slot vergeben wurde.
  const perJobPerDayCount = new Map(); // key: `${job_id}|${dateIndex}` -> int
  const lastJobDay = new Map();        // key: job_id -> letzter dateIndex
  const usedDates = new Set();
  const assignments = {};
  const unscheduled = [];
  let skippedConflicts = 0;

  const SAFETY_LIMIT = 50000;
  const MAX_SCHEDULE_HORIZON_DAYS = 366;

  let cursor = 0;
  for (const item of ordered) {
    const jobKey = item.job_id || 'unknown';
    let placed = false;
    let iterations = 0;
    while (!placed && iterations < SAFETY_LIMIT) {
      iterations += 1;
      const dayIndex = Math.floor(cursor / slots.length);
      if (dayIndex > MAX_SCHEDULE_HORIZON_DAYS) break;
      const slotIndex = cursor % slots.length;

      const jobDayKey = `${jobKey}|${dayIndex}`;
      const usedToday = perJobPerDayCount.get(jobDayKey) || 0;
      const lastDay = lastJobDay.get(jobKey);
      const intervalOk = lastDay === undefined || (dayIndex - lastDay) >= minInterval;

      if (usedToday < maxPerDay && intervalOk) {
        const slot = slots[slotIndex];
        // Berechne Ziel-Datum in Timezone, ausgehend vom Starttag + dayIndex.
        const target = new Date(Date.UTC(sy, sm - 1, sd));
        target.setUTCDate(target.getUTCDate() + dayIndex);
        const iso = zonedTimeToIso(
          target.getUTCFullYear(),
          target.getUTCMonth() + 1,
          target.getUTCDate(),
          slot.hours,
          slot.minutes,
          timeZone,
        );
        const isoKey = normalizeIsoKey(iso);
        if (isoKey && occupied.has(isoKey)) {
          // Slot ist bereits belegt (z. B. von einem hochgeladenen Post) —
          // naechsten Kandidaten probieren.
          skippedConflicts += 1;
          cursor += 1;
          continue;
        }
        const isoDate = new Date(iso);
        if (isoDate.getTime() <= earliestAllowedTime) {
          // Zu knappe Slots koennen bei grossen Batches waehrend des Uploads verfallen.
          cursor += 1;
          continue;
        }
        assignments[item.id] = iso;
        if (isoKey) occupied.add(isoKey);
        perJobPerDayCount.set(jobDayKey, usedToday + 1);
        lastJobDay.set(jobKey, dayIndex);
        usedDates.add(iso);
        placed = true;
      } else {
        // Suche den naechsten freien Cursor, an dem diese Job-ID wieder
        // einen Slot bekommen kann.
        cursor += 1;
      }
    }
    if (!placed) {
      unscheduled.push(item.id);
    }
  }

  return {
    assignments,
    scheduledCount: Object.keys(assignments).length,
    unscheduled,
    usedDates: Array.from(usedDates).sort(),
    skipped: skippedConflicts,
  };
};

// --- /Auto-Schedule helpers ------------------------------------------------

const buildInitialEditorState = (entry) => ({
  scheduled_date: formatDateTimeInputValue(entry?.scheduled_date || entry?.assigned_scheduled_date || ''),
  title: entry?.title || entry?.clip_title || '',
  description: entry?.description || entry?.clip_description || '',
  first_comment: entry?.first_comment || '',
  timezone: entry?.timezone || 'UTC',
  platforms: (entry?.requested_platforms || []).map(normalizePlatformKey),
  instagram_share_mode: entry?.request_settings?.instagram_share_mode || 'CUSTOM',
  instagram_collaborators: entry?.request_settings?.instagram_collaborators || '',
  tiktok_post_mode: entry?.request_settings?.tiktok_post_mode || 'DIRECT_POST',
  tiktok_is_aigc: !!entry?.request_settings?.tiktok_is_aigc,
  facebook_page_id: entry?.request_settings?.facebook_page_id || '',
  pinterest_board_id: entry?.request_settings?.pinterest_board_id || '',
});

const DEFAULT_AUTO_SCHEDULE_TIMEZONE = 'Europe/Berlin';
const DEFAULT_AUTO_SCHEDULE_SLOTS = '06:00; 12:00; 17:00; 21:00';
const DEFAULT_AUTO_MIN_JOB_INTERVAL_DAYS = 2;
const DEFAULT_AUTO_MAX_PER_JOB_PER_DAY = 1;

const buildDefaultSchedulerSettings = (defaultPostSettings) => ({
  platforms: { ...(defaultPostSettings?.platforms || {}) },
  firstComment: '',
  timezone: defaultPostSettings?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  instagramShareMode: defaultPostSettings?.instagramShareMode || 'CUSTOM',
  tiktokPostMode: defaultPostSettings?.tiktokPostMode || 'DIRECT_POST',
  tiktokIsAigc: !!defaultPostSettings?.tiktokIsAigc,
  facebookPageId: defaultPostSettings?.facebookPageId || '',
  pinterestBoardId: defaultPostSettings?.pinterestBoardId || '',
  autoTimezone: DEFAULT_AUTO_SCHEDULE_TIMEZONE,
  autoSlots: DEFAULT_AUTO_SCHEDULE_SLOTS,
  autoMinJobIntervalDays: DEFAULT_AUTO_MIN_JOB_INTERVAL_DAYS,
  autoMaxPerJobPerDay: DEFAULT_AUTO_MAX_PER_JOB_PER_DAY,
});

const encodeDragPayload = (payload) => JSON.stringify(payload);
const decodeDragPayload = (value) => {
  try {
    const parsed = JSON.parse(value || '{}');
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed;
  } catch (error) {
    return null;
  }
};

export default function UploadPostCalendarModal({
  isOpen,
  title,
  events,
  loading,
  error,
  onClose,
  onRefresh,
  onSaveEvent,
  onDeleteEvent,
  onResolveRemotePreview,
  onRescheduleEvent,
  onRescheduleAll,
  showRescheduleAll = false,
  rescheduleAllBusy = false,
  pendingItems = [],
  pendingSummary = null,
  defaultPostSettings = null,
  onSavePendingItem,
  onSchedulePendingItems,
  showPendingScheduler = false,
  vendorCalendarComplete = true,
  pendingOperationProgress = null,
  onRepairPodcastCampaigns,
  podcastCampaignRepairBusy = false,
  podcastCampaignRepairStatus = null,
}) {
  const [viewMode, setViewMode] = useState('month');
  const [cursorDate, setCursorDate] = useState(() => new Date());
  const [selectedEntryKey, setSelectedEntryKey] = useState('');
  const [editorState, setEditorState] = useState(buildInitialEditorState(null));
  const [draggedPayload, setDraggedPayload] = useState('');
  const [savingAction, setSavingAction] = useState('');
  const [actionError, setActionError] = useState('');
  const [isPendingSectionOpen, setIsPendingSectionOpen] = useState(true);
  const [isPendingSettingsOpen, setIsPendingSettingsOpen] = useState(true);
  const [pendingGroupState, setPendingGroupState] = useState({});
  const [draftAssignments, setDraftAssignments] = useState({});
  const [scheduleSettings, setScheduleSettings] = useState(buildDefaultSchedulerSettings(defaultPostSettings));
  const [pendingScheduleBusy, setPendingScheduleBusy] = useState(false);
  const [pendingScheduleStatus, setPendingScheduleStatus] = useState(null);
  const [pendingStatusFilter, setPendingStatusFilter] = useState('all');
  const [pendingAssignmentFilter, setPendingAssignmentFilter] = useState('all');
  const [pendingJobFilter, setPendingJobFilter] = useState('all');
  const [selectedPendingItemIds, setSelectedPendingItemIds] = useState([]);
  const [autoScheduleStatus, setAutoScheduleStatus] = useState(null);
  const [resolvedRemotePreviewUrls, setResolvedRemotePreviewUrls] = useState({});
  const [remotePreviewErrors, setRemotePreviewErrors] = useState({});
  const [remotePreviewBusyKey, setRemotePreviewBusyKey] = useState('');

  useEffect(() => {
    setScheduleSettings(buildDefaultSchedulerSettings(defaultPostSettings));
  }, [defaultPostSettings]);

  const sortedEvents = useMemo(() => {
    return [...(events || [])]
      .map((event) => ({ ...event, kind: 'event', entryKey: `event:${event.id}` }))
      .sort((left, right) => new Date(left.scheduled_date || 0).getTime() - new Date(right.scheduled_date || 0).getTime());
  }, [events]);

  const normalizedPendingItems = useMemo(() => {
    return (pendingItems || []).map((item) => ({
      ...item,
      kind: 'pending',
      assigned_scheduled_date: draftAssignments[item.id] || '',
      scheduled_date: draftAssignments[item.id] || '',
      entryKey: `pending:${item.id}`,
      visual_status: draftAssignments[item.id] ? 'assigned' : (item.status || 'ready'),
    }));
  }, [pendingItems, draftAssignments]);

  const assignedPendingCalendarItems = useMemo(() => {
    return normalizedPendingItems
      .filter((item) => item.assigned_scheduled_date)
      .sort((left, right) => new Date(left.assigned_scheduled_date || 0).getTime() - new Date(right.assigned_scheduled_date || 0).getTime());
  }, [normalizedPendingItems]);

  const filteredPendingItems = useMemo(() => {
    return normalizedPendingItems.filter((item) => {
      if (pendingStatusFilter === 'failed' && item.status !== 'failed') return false;
      if (pendingStatusFilter === 'ready' && item.status === 'failed') return false;
      if (pendingAssignmentFilter === 'assigned' && !item.assigned_scheduled_date) return false;
      if (pendingAssignmentFilter === 'unassigned' && item.assigned_scheduled_date) return false;
      if (pendingJobFilter !== 'all' && item.job_id !== pendingJobFilter) return false;
      return true;
    });
  }, [normalizedPendingItems, pendingAssignmentFilter, pendingJobFilter, pendingStatusFilter]);

  const groupedPendingItems = useMemo(() => {
    const grouped = filteredPendingItems.reduce((acc, item) => {
      const key = item.job_id || 'unknown';
      const group = acc.get(key) || {
        jobId: item.job_id,
        label: item.job_label || item.job_id,
        items: [],
      };
      group.items.push(item);
      acc.set(key, group);
      return acc;
    }, new Map());
    return Array.from(grouped.values()).sort((left, right) => left.label.localeCompare(right.label, 'de', { sensitivity: 'base' }));
  }, [filteredPendingItems]);

  const availablePendingJobs = useMemo(() => {
    const groups = normalizedPendingItems.reduce((acc, item) => {
      const key = item.job_id || 'unknown';
      if (!acc.has(key)) {
        acc.set(key, {
          jobId: item.job_id,
          label: item.job_label || item.job_id,
        });
      }
      return acc;
    }, new Map());
    return Array.from(groups.values()).sort((left, right) => left.label.localeCompare(right.label, 'de', { sensitivity: 'base' }));
  }, [normalizedPendingItems]);

  const allCalendarEntries = useMemo(() => {
    return [...sortedEvents, ...assignedPendingCalendarItems]
      .sort((left, right) => new Date(left.scheduled_date || 0).getTime() - new Date(right.scheduled_date || 0).getTime());
  }, [sortedEvents, assignedPendingCalendarItems]);

  const selectedEntry = useMemo(
    () => allCalendarEntries.find((item) => item.entryKey === selectedEntryKey)
      || normalizedPendingItems.find((item) => item.entryKey === selectedEntryKey)
      || null,
    [allCalendarEntries, normalizedPendingItems, selectedEntryKey]
  );

  const selectedEvent = selectedEntry?.kind === 'event' ? selectedEntry : null;
  const selectedPendingItem = selectedEntry?.kind === 'pending' ? selectedEntry : null;
  const selectedPreviewUrl = useMemo(() => {
    const resolvedRemote = selectedEvent ? resolvedRemotePreviewUrls[selectedEvent.id] : '';
    return resolveEntryPreviewUrl({
      ...(selectedEntry || {}),
      remote_preview_url: resolvedRemote || selectedEntry?.remote_preview_url || '',
    });
  }, [resolvedRemotePreviewUrls, selectedEntry, selectedEvent]);
  const selectedMediaBadge = useMemo(() => resolveEntryMediaBadge(selectedEntry), [selectedEntry]);
  const SelectedMediaIcon = selectedMediaBadge.icon;

  useEffect(() => {
    if (!isOpen) return;
    if (selectedEntryKey) return;
    const firstEntry = allCalendarEntries[0] || normalizedPendingItems[0] || null;
    if (firstEntry) {
      setSelectedEntryKey(firstEntry.entryKey);
    }
  }, [allCalendarEntries, isOpen, normalizedPendingItems, selectedEntryKey]);

  useEffect(() => {
    if (!isOpen) return;
    if (!sortedEvents.length) return;
    const now = Date.now();
    const nextUpcoming = sortedEvents.find((entry) => {
      const timestamp = new Date(entry.scheduled_date || '').getTime();
      return Number.isFinite(timestamp) && timestamp >= now;
    }) || sortedEvents[0];
    const nextDate = new Date(nextUpcoming.scheduled_date || '');
    if (!Number.isNaN(nextDate.getTime())) {
      setCursorDate(nextDate);
    }
  }, [isOpen, sortedEvents]);

  useEffect(() => {
    setEditorState(buildInitialEditorState(selectedEntry));
    setActionError('');
  }, [selectedEntry]);

  useEffect(() => {
    if (!isOpen) {
      setSavingAction('');
      setDraggedPayload('');
      setActionError('');
      setPendingScheduleStatus(null);
      setRemotePreviewBusyKey('');
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    if (!selectedEvent) return;
    if (!onResolveRemotePreview) return;
    if (selectedEvent.has_local_media) return;
    if (selectedPreviewUrl) return;
    if (!selectedEvent.vendor_job_id) return;
    if (remotePreviewErrors[selectedEvent.id]) return;

    let cancelled = false;
    setRemotePreviewBusyKey(selectedEvent.id);
    setRemotePreviewErrors((prev) => {
      if (!prev[selectedEvent.id]) return prev;
      const next = { ...prev };
      delete next[selectedEvent.id];
      return next;
    });

    onResolveRemotePreview(selectedEvent)
      .then((payload) => {
        if (cancelled) return;
        const previewUrl = String(payload?.preview_url || payload?.event?.remote_preview_url || '').trim();
        if (previewUrl) {
          setResolvedRemotePreviewUrls((prev) => ({ ...prev, [selectedEvent.id]: previewUrl }));
          setRemotePreviewErrors((prev) => {
            const next = { ...prev };
            delete next[selectedEvent.id];
            return next;
          });
        } else {
          setRemotePreviewErrors((prev) => ({
            ...prev,
            [selectedEvent.id]: payload?.message || 'Upload-Post liefert fuer diesen Slot aktuell keine Preview-URL.',
          }));
        }
      })
      .catch((error) => {
        if (cancelled) return;
        setRemotePreviewErrors((prev) => ({
          ...prev,
          [selectedEvent.id]: error?.message || 'Preview von Upload-Post konnte nicht geladen werden.',
        }));
      })
      .finally(() => {
        if (!cancelled) setRemotePreviewBusyKey('');
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen, onResolveRemotePreview, remotePreviewErrors, selectedEvent, selectedPreviewUrl]);

  useEffect(() => {
    setSelectedPendingItemIds((prev) => {
      const next = prev.filter((id) => normalizedPendingItems.some((item) => item.id === id));
      if (next.length === prev.length && next.every((value, index) => value === prev[index])) {
        return prev;
      }
      return next;
    });
  }, [normalizedPendingItems]);

  if (!isOpen) return null;

  const monthGrid = buildMonthGrid(cursorDate);
  const weekDays = buildWeekDays(cursorDate);
  const quarterHourSlots = buildDayQuarterHourSlots(cursorDate);
  const dayEntries = allCalendarEntries.filter((entry) => {
    const eventDate = new Date(entry.scheduled_date);
    return !Number.isNaN(eventDate.getTime()) && isSameDay(eventDate, cursorDate);
  });

  const navigate = (direction) => {
    setCursorDate((prev) => {
      const next = new Date(prev);
      if (viewMode === 'month') next.setMonth(next.getMonth() + direction);
      else if (viewMode === 'week') next.setDate(next.getDate() + direction * 7);
      else next.setDate(next.getDate() + direction);
      return next;
    });
  };

  const entriesForDay = (date) => allCalendarEntries.filter((entry) => {
    const eventDate = new Date(entry.scheduled_date);
    return !Number.isNaN(eventDate.getTime()) && isSameDay(eventDate, date);
  });

  const entriesForSlot = (slotDate) => {
    const slotTime = slotDate.getTime();
    return dayEntries.filter((entry) => {
      const bucket = floorToQuarterHour(entry.scheduled_date);
      return bucket && bucket.getTime() === slotTime;
    });
  };

  const assignedDraftCount = assignedPendingCalendarItems.length;
  const filteredAssignedDraftCount = filteredPendingItems.filter((item) => item.assigned_scheduled_date).length;
  const filteredFailedCount = filteredPendingItems.filter((item) => item.status === 'failed').length;
  const allFilteredPendingSelected = filteredPendingItems.length > 0
    && filteredPendingItems.every((item) => selectedPendingItemIds.includes(item.id));

  const handleAssignPendingItems = (itemIds, date, dropMode = 'day') => {
    const orderedIds = (Array.isArray(itemIds) ? itemIds : [itemIds]).filter(Boolean);
    if (!orderedIds.length) return;

    const pendingById = new Map(normalizedPendingItems.map((item) => [item.id, item]));
    const nextAssignments = {};

    orderedIds.forEach((itemId, index) => {
      const pendingItem = pendingById.get(itemId);
      if (!pendingItem) return;
      let nextDate;
      if (dropMode === 'slot') {
        nextDate = addMinutes(new Date(date), index * 15);
      } else {
        nextDate = new Date(buildDraftAssignmentDate(date, pendingItem.assigned_scheduled_date));
        nextDate = addMinutes(nextDate, index * 15);
      }
      const rounded = floorToQuarterHour(nextDate) || nextDate;
      nextAssignments[itemId] = rounded.toISOString();
    });

    setDraftAssignments((prev) => ({ ...prev, ...nextAssignments }));
    setSelectedEntryKey(`pending:${orderedIds[0]}`);
    setPendingScheduleStatus(null);
  };

  const handleAssignPendingItem = (item, nextIsoDate) => {
    handleAssignPendingItems([item.id], new Date(nextIsoDate), 'slot');
  };

  const handleUnassignPendingItem = (itemId) => {
    setDraftAssignments((prev) => {
      if (!(itemId in prev)) return prev;
      const next = { ...prev };
      delete next[itemId];
      return next;
    });
    setPendingScheduleStatus(null);
  };

  const handleDropOnDate = async (date, dropMode = 'day', dragPayloadValue = '') => {
    const payload = decodeDragPayload(dragPayloadValue || draggedPayload);
    if (!payload?.id || !payload?.kind) return;

    if (payload.kind === 'event') {
      const event = sortedEvents.find((item) => item.id === payload.id);
      if (!event) return;
      if (event.is_blocked_slot) {
        setActionError('Dieser Upload-Post Queue-Slot ist blockiert und kann hier nicht verschoben werden.');
        setDraggedPayload('');
        return;
      }
      const baseDate = dropMode === 'slot'
        ? new Date(date)
        : buildDraftAssignmentDate(date, event.scheduled_date);
      const nextIsoDate = dropMode === 'slot'
        ? new Date(date).toISOString()
        : new Date(baseDate).toISOString();
      setSavingAction(`move:${event.id}`);
      setActionError('');
      try {
        await onSaveEvent({
          event,
          payload: {
            scheduled_date: nextIsoDate,
            title: event.title || '',
            description: event.description || '',
            first_comment: event.first_comment || '',
            timezone: event.timezone || 'UTC',
            platforms: event.requested_platforms || [],
            instagram_share_mode: event.request_settings?.instagram_share_mode,
            instagram_collaborators: event.request_settings?.instagram_collaborators || '',
            tiktok_post_mode: event.request_settings?.tiktok_post_mode,
            tiktok_is_aigc: !!event.request_settings?.tiktok_is_aigc,
            facebook_page_id: event.request_settings?.facebook_page_id || '',
            pinterest_board_id: event.request_settings?.pinterest_board_id || '',
          },
        });
      } catch (error) {
        setActionError(error.message || 'Kalender-Eintrag konnte nicht verschoben werden.');
      } finally {
        setSavingAction('');
        setDraggedPayload('');
      }
      return;
    }

    const pendingIds = Array.isArray(payload.ids) && payload.ids.length
      ? payload.ids
      : [payload.id];
    handleAssignPendingItems(pendingIds, date, dropMode);
    setDraggedPayload('');
  };

  const togglePendingSelection = (itemId, nextChecked) => {
    setSelectedPendingItemIds((prev) => {
      const exists = prev.includes(itemId);
      if (nextChecked && !exists) return [...prev, itemId];
      if (!nextChecked && exists) return prev.filter((id) => id !== itemId);
      return prev;
    });
  };

  const toggleSelectAllFiltered = () => {
    setSelectedPendingItemIds((prev) => {
      if (allFilteredPendingSelected) {
        return prev.filter((id) => !filteredPendingItems.some((item) => item.id === id));
      }
      const next = new Set(prev);
      filteredPendingItems.forEach((item) => next.add(item.id));
      return Array.from(next);
    });
  };

  const handleEditorSave = async () => {
    if (!selectedEntry) return;
    setActionError('');

    if (selectedPendingItem) {
      if (!onSavePendingItem) return;
      setSavingAction(`save:${selectedPendingItem.id}`);
      try {
        await onSavePendingItem({
          item: selectedPendingItem,
          payload: {
            title: editorState.title,
            description: editorState.description,
          },
        });
        setPendingScheduleStatus({ type: 'success', message: 'Clip-Metadaten gespeichert.' });
      } catch (error) {
        setActionError(error.message || 'Clip konnte nicht gespeichert werden.');
      } finally {
        setSavingAction('');
      }
      return;
    }

    if (!selectedEvent) return;
    if (selectedEvent.is_blocked_slot) return;
    setSavingAction(`save:${selectedEvent.id}`);
    try {
      await onSaveEvent({
        event: selectedEvent,
        payload: {
          ...editorState,
          scheduled_date: parseDateInputToIso(editorState.scheduled_date),
        },
      });
    } catch (error) {
      setActionError(error.message || 'Kalender-Eintrag konnte nicht gespeichert werden.');
    } finally {
      setSavingAction('');
    }
  };

  const handleDelete = async () => {
    if (!selectedEvent) return;
    if (selectedEvent.is_blocked_slot) return;
    const confirmed = window.confirm(`Post wirklich loeschen?\n\n${selectedEvent.title || selectedEvent.clip_label}`);
    if (!confirmed) return;
    setSavingAction(`delete:${selectedEvent.id}`);
    setActionError('');
    try {
      await onDeleteEvent(selectedEvent);
      setSelectedEntryKey('');
    } catch (error) {
      setActionError(error.message || 'Kalender-Eintrag konnte nicht geloescht werden.');
    } finally {
      setSavingAction('');
    }
  };

  const handleReschedule = async () => {
    if (!selectedEvent) return;
    if (selectedEvent.is_blocked_slot) return;
    const recreateAvailable = !!selectedEvent.can_recreate;
    const isVendorOnly = selectedEvent.event_source === 'vendor_only' || !recreateAvailable;
    if (isVendorOnly && !onSaveEvent) return;
    if (!isVendorOnly && !onRescheduleEvent) return;
    const confirmLabel = isVendorOnly ? 'verschieben / neu schedulen' : 'neu hochladen und neu schedulen';
    const confirmed = window.confirm(
      `Post wirklich ${confirmLabel}?\n\n${selectedEvent.title || selectedEvent.clip_label}`,
    );
    if (!confirmed) return;
    setSavingAction(`reschedule:${selectedEvent.id}`);
    setActionError('');
    try {
      const handler = isVendorOnly ? onSaveEvent : onRescheduleEvent;
      await handler({
        event: selectedEvent,
        payload: {
          ...editorState,
          scheduled_date: parseDateInputToIso(editorState.scheduled_date),
          mode: isVendorOnly ? 'patch' : 'recreate',
        },
      });
    } catch (error) {
      setActionError(error.message || (isVendorOnly
        ? 'Kalender-Eintrag konnte nicht verschoben werden.'
        : 'Kalender-Eintrag konnte nicht neu hochgeladen werden.'));
    } finally {
      setSavingAction('');
    }
  };

  const handleAutoAssignSelectedDrafts = () => {
    setAutoScheduleStatus(null);
    if (!vendorCalendarComplete) {
      setAutoScheduleStatus({
        type: 'error',
        message: 'Upload-Post-Kalender ist nicht vollstaendig synchronisiert. Bitte aktualisieren, bevor automatisch verteilt wird.',
      });
      return;
    }
    const selectedIds = selectedPendingItemIds.length
      ? selectedPendingItemIds
      : filteredPendingItems.map((item) => item.id);
    if (!selectedIds.length) {
      setAutoScheduleStatus({
        type: 'error',
        message: 'Bitte zuerst Shorts im Filter auswaehlen oder die Auswahl sichtbarer Shorts aktivieren.',
      });
      return;
    }
    const selectedSet = new Set(selectedIds);
    const items = normalizedPendingItems.filter((item) => selectedSet.has(item.id));
    let slots;
    try {
      slots = parseAutoScheduleSlots(scheduleSettings.autoSlots);
    } catch (error) {
      setAutoScheduleStatus({ type: 'error', message: error.message || 'Slot-Liste ungueltig.' });
      return;
    }
    const timeZone = (scheduleSettings.autoTimezone || DEFAULT_AUTO_SCHEDULE_TIMEZONE).trim()
      || DEFAULT_AUTO_SCHEDULE_TIMEZONE;

    // Belegte Slots sammeln:
    //  1) bereits hochgeladene/geplante Kalender-Events (von Upload-Post),
    //  2) manuell zugewiesene Drafts in dieser Session (andere Jobs),
    //  3) Drafts aus dieser Auswahl, die schon eine assigned_scheduled_date
    //     haben und nicht ersetzt werden sollen.
    const existingDates = [];
    for (const event of sortedEvents || []) {
      const iso = event?.scheduled_date;
      if (iso) existingDates.push(iso);
    }
    for (const item of normalizedPendingItems) {
      const isInSelection = selectedSet.has(item.id);
      const iso = item.assigned_scheduled_date;
      if (!iso) continue;
      if (isInSelection) continue; // wir vergeben ohnehin neu
      existingDates.push(iso);
    }

    let result;
    try {
      result = buildAutoScheduleAssignments({
        items,
        slots,
        timeZone,
        minJobIntervalDays: scheduleSettings.autoMinJobIntervalDays,
        maxPerJobPerDay: scheduleSettings.autoMaxPerJobPerDay,
        existingDates,
      });
    } catch (error) {
      setAutoScheduleStatus({ type: 'error', message: error.message || 'Auto-Schedule fehlgeschlagen.' });
      return;
    }
    if (!result.scheduledCount) {
      setAutoScheduleStatus({
        type: 'error',
        message: 'Es konnte kein zukuenftiger Slot fuer die ausgewaehlten Shorts gefunden werden.',
      });
      return;
    }
    setDraftAssignments((prev) => ({ ...prev, ...result.assignments }));
    const firstDates = result.usedDates.slice(0, 4).map((iso) =>
      formatDateTimeInputValue(iso).replace('T', ' ')
    );
    const firstDatesLabel = firstDates.length ? firstDates.join(', ') : '—';
    const conflictNote = result.skipped
      ? ` (${result.skipped} belegte Slots uebersprungen)`
      : '';
    if (result.unscheduled.length) {
      setAutoScheduleStatus({
        type: 'warning',
        message: `${result.scheduledCount} Shorts automatisch verteilt, ${result.unscheduled.length} ohne Slot${conflictNote}. Erste Slots: ${firstDatesLabel}.`,
      });
    } else {
      setAutoScheduleStatus({
        type: 'success',
        message: `${result.scheduledCount} Shorts automatisch verteilt${conflictNote}. Erste Slots: ${firstDatesLabel}.`,
      });
    }
  };

  const handleScheduleAssignedDrafts = async () => {
    if (!onSchedulePendingItems) return;
    const assignedItems = normalizedPendingItems
      .filter((item) => item.assigned_scheduled_date)
      .map((item) => ({ ...item, scheduled_date: item.assigned_scheduled_date }));
    if (!assignedItems.length) {
      setPendingScheduleStatus({ type: 'error', message: 'Bitte zuerst gelbe Draft-Slots im Kalender zuordnen.' });
      return;
    }

    setPendingScheduleBusy(true);
    setPendingScheduleStatus({ type: 'info', message: 'Zugeordnete Shorts werden jetzt eingeplant...' });
    try {
      const result = await onSchedulePendingItems({
        items: assignedItems,
        settings: scheduleSettings,
      });
      const startedCount = Array.isArray(result?.startedIds) ? result.startedIds.length : 0;
      const failedGroups = Array.isArray(result?.failedGroups) ? result.failedGroups : [];
      if (startedCount > 0) {
        setDraftAssignments((prev) => {
          const next = { ...prev };
          for (const id of result.startedIds) delete next[id];
          return next;
        });
      }
      if (failedGroups.length > 0) {
        const firstError = failedGroups[0]?.error || 'Einige Jobs konnten nicht gestartet werden.';
        setPendingScheduleStatus({
          type: startedCount > 0 ? 'warning' : 'error',
          message: startedCount > 0
            ? `${startedCount} Shorts angestossen, aber ${failedGroups.length} Job${failedGroups.length === 1 ? '' : 's'} haben Fehler: ${firstError}`
            : firstError,
        });
      } else {
        setPendingScheduleStatus({ type: 'success', message: `${startedCount} Shorts zum Schedulen angestossen.` });
      }
    } catch (error) {
      setPendingScheduleStatus({ type: 'error', message: error.message || 'Sammel-Schedule fehlgeschlagen.' });
    } finally {
      setPendingScheduleBusy(false);
    }
  };

  const renderCalendarPill = (entry) => {
    const isSelected = selectedEntryKey === entry.entryKey;
    const isBusy = savingAction.includes(entry.id);
    const visualStatus = entry.kind === 'pending' ? entry.visual_status : entry.status;
    const mediaBadge = resolveEntryMediaBadge(entry);
    const MediaIcon = mediaBadge.icon;
    return (
      <button
        key={entry.entryKey}
        type="button"
        draggable
        onDragStart={(dragEvent) => {
          dragEvent.dataTransfer.effectAllowed = 'move';
          const payload = encodeDragPayload({ kind: entry.kind, id: entry.kind === 'event' ? entry.id : entry.id });
          dragEvent.dataTransfer.setData('text/plain', payload);
          setDraggedPayload(payload);
        }}
        onDragEnd={() => setDraggedPayload('')}
        onClick={() => setSelectedEntryKey(entry.entryKey)}
        className={`w-full rounded-lg border px-2 py-1.5 text-left text-[11px] transition-colors ${resolveStatusStyle(visualStatus)} ${isSelected ? 'ring-1 ring-white/30' : ''}`}
        title={mediaBadge.label}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1 truncate font-semibold">
            {entry.kind === 'event' && entry.is_rescheduled ? <RefreshCcw size={11} className="shrink-0 opacity-80" /> : null}
            <MediaIcon size={11} className={`shrink-0 ${mediaBadge.className}`} />
            <span className="truncate">{entry.title || entry.clip_label}</span>
          </span>
          <span className="shrink-0 text-[10px] opacity-80">{isBusy ? '...' : formatTimeLabel(entry.scheduled_date)}</span>
        </div>
        <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px] opacity-80">
          <span className="truncate">{entry.job_label}</span>
          {entry.kind === 'pending' ? <span className="shrink-0 uppercase tracking-wide">Draft</span> : null}
        </div>
      </button>
    );
  };

  const renderDropDay = (date, isMuted = false, options = {}) => {
    const dayItems = entriesForDay(date);
    const maxVisible = typeof options.maxVisible === 'number' ? options.maxVisible : 4;
    const visibleItems = maxVisible > 0 ? dayItems.slice(0, maxVisible) : dayItems;
    return (
      <div
        key={date.toISOString()}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          const payload = event.dataTransfer.getData('text/plain') || draggedPayload;
          setDraggedPayload(payload);
          handleDropOnDate(date, 'day', payload);
        }}
        className={`min-h-[7.5rem] rounded-xl border p-2 ${isMuted ? 'border-white/5 bg-black/20 text-zinc-600' : 'border-white/10 bg-white/5 text-zinc-200'}`}
      >
        <div className="mb-2 flex items-center justify-between text-[11px]">
          <button
            type="button"
            onClick={() => {
              setCursorDate(new Date(date));
              setViewMode('day');
            }}
            className="font-semibold hover:text-cyan-200"
          >
            {date.getDate()}
          </button>
          {isSameDay(date, new Date()) ? <span className="rounded-full bg-primary/20 px-2 py-0.5 text-[10px] text-primary">Heute</span> : null}
        </div>
        <div className="space-y-1.5">
          {visibleItems.map(renderCalendarPill)}
          {dayItems.length > visibleItems.length ? <div className="text-[10px] text-zinc-500">+{dayItems.length - visibleItems.length} weitere</div> : null}
        </div>
      </div>
    );
  };

  return createPortal(
    <div className="fixed inset-0 z-[4200] flex items-stretch justify-center bg-black/70 backdrop-blur-sm">
      <div className="flex h-full w-full flex-col overflow-hidden bg-[#0b0b0d] text-white md:m-3 md:h-[calc(100%-1.5rem)] md:rounded-3xl md:border md:border-white/10">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-4 md:px-6">
          <div>
            <div className="flex items-center gap-2 text-white">
              <CalendarDays size={18} className="text-cyan-300" />
              <h2 className="text-lg font-semibold">{title}</h2>
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              Persistierte Upload-Post-Slots verwalten und gelbe Draft-Zuordnungen gesammelt planen.
            </p>
            {podcastCampaignRepairStatus?.message ? (
              <p className={`mt-1 text-xs ${
                podcastCampaignRepairStatus.type === 'error'
                  ? 'text-red-300'
                  : podcastCampaignRepairStatus.type === 'warning'
                    ? 'text-amber-300'
                    : podcastCampaignRepairStatus.type === 'success'
                      ? 'text-emerald-300'
                      : 'text-cyan-300'
              }`}>
                {podcastCampaignRepairStatus.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {VIEW_MODES.map((mode) => (
              <button
                key={mode.key}
                type="button"
                onClick={() => setViewMode(mode.key)}
                className={`rounded-full border px-3 py-1.5 text-xs ${viewMode === mode.key ? 'border-cyan-500/30 bg-cyan-500/15 text-cyan-100' : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'}`}
              >
                {mode.label}
              </button>
            ))}
            {onRepairPodcastCampaigns ? (
              <button
                type="button"
                onClick={() => {
                  Promise.resolve(onRepairPodcastCampaigns()).catch(() => {});
                }}
                disabled={loading || podcastCampaignRepairBusy}
                className="inline-flex items-center gap-2 rounded-xl border border-amber-400/25 bg-amber-400/10 px-3 py-2 text-sm text-amber-100 hover:bg-amber-400/15 disabled:opacity-50"
              >
                {podcastCampaignRepairBusy ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
                Instagram CTA + Relay reparieren
              </button>
            ) : null}
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200 hover:bg-white/10 disabled:opacity-50"
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
              Aktualisieren
            </button>
            {showRescheduleAll && onRescheduleAll ? (
              <button
                type="button"
                onClick={onRescheduleAll}
                disabled={loading || rescheduleAllBusy}
                className="inline-flex items-center gap-2 rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/10 px-3 py-2 text-sm text-fuchsia-100 hover:bg-fuchsia-500/15 disabled:opacity-50"
              >
                {(loading || rescheduleAllBusy) ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
                Reschedule all
              </button>
            ) : null}
            <button
              type="button"
              onClick={onClose}
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200 hover:bg-white/10"
            >
              <X size={15} />
              Schliessen
            </button>
          </div>
        </div>

        <div className="flex flex-1 min-h-0 flex-col xl:flex-row">
          <div className="flex min-h-0 flex-1 flex-col border-b border-white/10 xl:border-b-0 xl:border-r xl:border-white/10">
            <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3 md:px-6">
              <button type="button" onClick={() => navigate(-1)} className="rounded-lg border border-white/10 bg-white/5 p-2 text-zinc-200 hover:bg-white/10">
                <ChevronLeft size={16} />
              </button>
              <div className="text-sm font-semibold text-white">{formatMonthLabel(cursorDate)}</div>
              <button type="button" onClick={() => navigate(1)} className="rounded-lg border border-white/10 bg-white/5 p-2 text-zinc-200 hover:bg-white/10">
                <ChevronRight size={16} />
              </button>
            </div>

            <div className={`flex-1 overflow-y-auto p-4 md:px-6 md:py-5 custom-scrollbar space-y-4 ${
              showPendingScheduler ? 'xl:grid xl:grid-cols-[380px_minmax(0,1fr)] xl:items-start xl:gap-4 xl:space-y-0' : ''
            }`}>
              {error ? (
                <div className={`rounded-2xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-200 ${showPendingScheduler ? 'xl:col-start-2' : ''}`}>{error}</div>
              ) : null}

              {!error && viewMode === 'month' && (
                <div className={`space-y-2 ${showPendingScheduler ? 'xl:col-start-2' : ''}`}>
                  <div className="mb-2 grid grid-cols-7 gap-2 text-center text-[11px] uppercase tracking-wide text-zinc-500">
                    {['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'].map((label) => <div key={label}>{label}</div>)}
                  </div>
                  <div className="grid grid-cols-7 gap-2">
                    {monthGrid.map((date) => renderDropDay(date, date.getMonth() !== cursorDate.getMonth(), { maxVisible: 4 }))}
                  </div>
                </div>
              )}

              {!error && viewMode === 'week' && (
                <div className={`grid gap-3 lg:grid-cols-7 ${showPendingScheduler ? 'xl:col-start-2' : ''}`}>
                  {weekDays.map((date) => (
                    <div key={date.toISOString()} className="space-y-2">
                      <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-center text-xs font-semibold text-zinc-200">
                        {formatDayHeader(date)}
                      </div>
                      {renderDropDay(date, false, { maxVisible: Number.POSITIVE_INFINITY })}
                    </div>
                  ))}
                </div>
              )}

              {!error && viewMode === 'day' && (
                <div className={`space-y-3 ${showPendingScheduler ? 'xl:col-start-2' : ''}`}>
                  <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white">
                    {formatDayHeader(cursorDate)}
                  </div>
                  <div className="grid gap-2">
                    {quarterHourSlots.map((slotDate) => {
                      const slotItems = entriesForSlot(slotDate);
                      return (
                        <div
                          key={slotDate.toISOString()}
                          onDragOver={(event) => event.preventDefault()}
                          onDrop={(event) => {
                            event.preventDefault();
                            const payload = event.dataTransfer.getData('text/plain') || draggedPayload;
                            setDraggedPayload(payload);
                            handleDropOnDate(slotDate, 'slot', payload);
                          }}
                          className="grid min-h-[4.25rem] grid-cols-[72px_1fr] gap-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2"
                        >
                          <div className="text-xs font-semibold text-zinc-400">{formatTimeLabel(slotDate)}</div>
                          <div className="space-y-1.5">
                            {slotItems.length ? slotItems.map(renderCalendarPill) : <div className="pt-1 text-[11px] text-zinc-600">Auf diesen 15-Minuten-Slot ziehen</div>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {showPendingScheduler ? (
                <div className="xl:col-start-1 xl:row-start-1 xl:max-h-[calc(100vh-12rem)] xl:overflow-y-auto xl:pr-1 custom-scrollbar">
                  <div className="rounded-2xl border border-white/10 bg-white/5 xl:sticky xl:top-0">
                    <button
                      type="button"
                      onClick={() => setIsPendingSectionOpen((prev) => !prev)}
                      className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                    >
                      <div>
                        <div className="text-sm font-semibold text-white">Multi-Post Queue</div>
                        <div className="mt-1 text-xs text-zinc-500">
                          {pendingSummary?.total_count || normalizedPendingItems.length} offene Shorts · {assignedDraftCount} gelb zugeordnet
                        </div>
                      </div>
                      <ChevronDown size={16} className={`text-zinc-400 transition-transform ${isPendingSectionOpen ? 'rotate-180' : ''}`} />
                    </button>

                    {isPendingSectionOpen ? (
                      <div className="border-t border-white/10 px-4 py-4 space-y-4">
                      <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-3 space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <div className="text-sm font-semibold text-white">Offene Shorts filtern</div>
                            <div className="mt-1 text-xs text-zinc-500">
                              {filteredPendingItems.length} sichtbar · {filteredFailedCount} failed · {filteredAssignedDraftCount} gelb zugeordnet
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={toggleSelectAllFiltered}
                              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-200 hover:bg-white/10"
                            >
                              {allFilteredPendingSelected ? 'Auswahl lösen' : 'Alle sichtbaren wählen'}
                            </button>
                            {selectedPendingItemIds.length ? (
                              <button
                                type="button"
                                onClick={() => setSelectedPendingItemIds([])}
                                className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-200 hover:bg-white/10"
                              >
                                Auswahl leeren
                              </button>
                            ) : null}
                          </div>
                        </div>

                        <div className="grid gap-3 md:grid-cols-3">
                          <div>
                            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Status</label>
                            <div className="flex flex-wrap gap-2">
                              {[
                                { key: 'all', label: 'Alle' },
                                { key: 'failed', label: 'Nur failed' },
                                { key: 'ready', label: 'Nur render-ready' },
                              ].map((option) => (
                                <button
                                  key={option.key}
                                  type="button"
                                  onClick={() => setPendingStatusFilter(option.key)}
                                  className={`rounded-full border px-3 py-1.5 text-xs ${pendingStatusFilter === option.key ? 'border-cyan-500/30 bg-cyan-500/15 text-cyan-100' : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'}`}
                                >
                                  {option.label}
                                </button>
                              ))}
                            </div>
                          </div>
                          <div>
                            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Zuordnung</label>
                            <div className="flex flex-wrap gap-2">
                              {[
                                { key: 'all', label: 'Alle' },
                                { key: 'unassigned', label: 'Nur offen' },
                                { key: 'assigned', label: 'Nur gelb' },
                              ].map((option) => (
                                <button
                                  key={option.key}
                                  type="button"
                                  onClick={() => setPendingAssignmentFilter(option.key)}
                                  className={`rounded-full border px-3 py-1.5 text-xs ${pendingAssignmentFilter === option.key ? 'border-cyan-500/30 bg-cyan-500/15 text-cyan-100' : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'}`}
                                >
                                  {option.label}
                                </button>
                              ))}
                            </div>
                          </div>
                          <div>
                            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Job</label>
                            <select
                              value={pendingJobFilter}
                              onChange={(event) => setPendingJobFilter(event.target.value)}
                              className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                            >
                              <option value="all">Alle Jobs</option>
                              {availablePendingJobs.map((job) => (
                                <option key={job.jobId} value={job.jobId}>{job.label}</option>
                              ))}
                            </select>
                          </div>
                        </div>

                        {selectedPendingItemIds.length ? (
                          <div className="rounded-xl border border-amber-400/20 bg-amber-400/8 px-3 py-2 text-xs text-amber-100">
                            {selectedPendingItemIds.length} Short{selectedPendingItemIds.length === 1 ? '' : 's'} ausgewählt. Wenn du jetzt einen davon auf einen Tag oder Slot ziehst, werden alle ausgewählten gemeinsam zugeordnet.
                          </div>
                        ) : null}
                      </div>

                      <div className="rounded-xl border border-white/10 bg-black/20">
                        <button
                          type="button"
                          onClick={() => setIsPendingSettingsOpen((prev) => !prev)}
                          className="flex w-full items-center justify-between gap-3 px-3 py-3 text-left"
                        >
                          <div>
                            <div className="text-sm font-semibold text-white">Sammel-Schedule Einstellungen</div>
                            <div className="mt-1 text-xs text-zinc-500">Plattformen, Kommentar und Posting-Optionen fuer alle gelben Zuordnungen.</div>
                          </div>
                          <ChevronDown size={16} className={`text-zinc-400 transition-transform ${isPendingSettingsOpen ? 'rotate-180' : ''}`} />
                        </button>
                        {isPendingSettingsOpen ? (
                          <div className="border-t border-white/10 px-3 py-3 space-y-4">
                            <div>
                              <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Plattformen</label>
                              <div className="grid grid-cols-2 gap-2">
                                {SOCIAL_PLATFORM_OPTIONS.map((platform) => {
                                  const checked = !!scheduleSettings.platforms?.[platform.key];
                                  return (
                                    <label key={platform.key} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200">
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={(event) => setScheduleSettings((prev) => ({
                                          ...prev,
                                          platforms: {
                                            ...(prev.platforms || {}),
                                            [platform.key]: event.target.checked,
                                          },
                                        }))}
                                        className="h-4 w-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                      />
                                      {platform.label}
                                    </label>
                                  );
                                })}
                              </div>
                            </div>

                            <div>
                              <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Erster Kommentar</label>
                              <textarea
                                value={scheduleSettings.firstComment}
                                onChange={(event) => setScheduleSettings((prev) => ({ ...prev, firstComment: event.target.value }))}
                                rows={2}
                                className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                              />
                            </div>

                            <div className="grid gap-3 md:grid-cols-2">
                              <div>
                                <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Timezone</label>
                                <input
                                  type="text"
                                  value={scheduleSettings.timezone}
                                  onChange={(event) => setScheduleSettings((prev) => ({ ...prev, timezone: event.target.value }))}
                                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                                />
                              </div>
                              <div>
                                <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Instagram-Modus</label>
                                <select
                                  value={scheduleSettings.instagramShareMode}
                                  onChange={(event) => setScheduleSettings((prev) => ({ ...prev, instagramShareMode: event.target.value }))}
                                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                                >
                                  {INSTAGRAM_SHARE_MODES.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
                                </select>
                              </div>
                            </div>

                            <div className="grid gap-3 md:grid-cols-2">
                              <div>
                                <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">TikTok-Modus</label>
                                <select
                                  value={scheduleSettings.tiktokPostMode}
                                  onChange={(event) => setScheduleSettings((prev) => ({ ...prev, tiktokPostMode: event.target.value }))}
                                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                                >
                                  {TIKTOK_POST_MODES.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
                                </select>
                              </div>
                              <div>
                                <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Facebook-Page-ID</label>
                                <input
                                  type="text"
                                  value={scheduleSettings.facebookPageId}
                                  onChange={(event) => setScheduleSettings((prev) => ({ ...prev, facebookPageId: event.target.value }))}
                                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                                />
                              </div>
                            </div>

                            <div className="grid gap-3 md:grid-cols-2">
                              <label className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200">
                                <input
                                  type="checkbox"
                                  checked={scheduleSettings.tiktokIsAigc}
                                  onChange={(event) => setScheduleSettings((prev) => ({ ...prev, tiktokIsAigc: event.target.checked }))}
                                  className="h-4 w-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                />
                                TikTok als KI-generiert markieren
                              </label>
                              <div>
                                <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Pinterest-Board-ID</label>
                                <input
                                  type="text"
                                  value={scheduleSettings.pinterestBoardId}
                                  onChange={(event) => setScheduleSettings((prev) => ({ ...prev, pinterestBoardId: event.target.value }))}
                                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                                />
                              </div>
                            </div>

                            <div className="rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-3 space-y-3">
                              <div>
                                <div className="text-xs font-semibold uppercase tracking-wide text-amber-100/90">Auto-Verteilung fuer gelbe Drafts</div>
                                <div className="mt-1 text-[11px] text-amber-100/70">
                                  Verteilt die aktuell ausgewaehlten Shorts (oder alle sichtbaren) automatisch auf Slots. Pro Job wird der Tagesabstand und das Tagesmaximum eingehalten.
                                </div>
                              </div>
                              <div className="grid gap-3 md:grid-cols-2">
                                <div>
                                  <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Slots (Berliner Zeit, ; oder , getrennt)</label>
                                  <input
                                    type="text"
                                    value={scheduleSettings.autoSlots}
                                    onChange={(event) => setScheduleSettings((prev) => ({ ...prev, autoSlots: event.target.value }))}
                                    placeholder="06:00; 12:00; 17:00; 21:00"
                                    className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-amber-300/40"
                                  />
                                </div>
                                <div>
                                  <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Zeitzone (IANA)</label>
                                  <input
                                    type="text"
                                    value={scheduleSettings.autoTimezone}
                                    onChange={(event) => setScheduleSettings((prev) => ({ ...prev, autoTimezone: event.target.value }))}
                                    placeholder="Europe/Berlin"
                                    className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-amber-300/40"
                                  />
                                </div>
                              </div>
                              <div className="grid gap-3 md:grid-cols-2">
                                <div>
                                  <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Min. Tage zwischen Clips vom selben Job</label>
                                  <input
                                    type="number"
                                    min="1"
                                    step="1"
                                    value={scheduleSettings.autoMinJobIntervalDays}
                                    onChange={(event) => setScheduleSettings((prev) => ({
                                      ...prev,
                                      autoMinJobIntervalDays: Math.max(1, Number(event.target.value) || 1),
                                    }))}
                                    className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-amber-300/40"
                                  />
                                </div>
                                <div>
                                  <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Max. Clips pro Job pro Tag</label>
                                  <input
                                    type="number"
                                    min="1"
                                    step="1"
                                    value={scheduleSettings.autoMaxPerJobPerDay}
                                    onChange={(event) => setScheduleSettings((prev) => ({
                                      ...prev,
                                      autoMaxPerJobPerDay: Math.max(1, Number(event.target.value) || 1),
                                    }))}
                                    className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-amber-300/40"
                                  />
                                </div>
                              </div>
                              {autoScheduleStatus ? (
                                <div className={`rounded-lg border px-3 py-2 text-xs ${
                                  autoScheduleStatus.type === 'success'
                                    ? 'border-green-500/20 bg-green-500/10 text-green-200'
                                    : autoScheduleStatus.type === 'warning'
                                      ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                                      : autoScheduleStatus.type === 'info'
                                        ? 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100'
                                        : 'border-red-500/20 bg-red-500/10 text-red-200'
                                }`}>
                                  {autoScheduleStatus.message}
                                </div>
                              ) : null}
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="text-[11px] text-amber-100/70">
                                  {vendorCalendarComplete
                                    ? <>Verteilt <span className="font-semibold">{selectedPendingItemIds.length || filteredPendingItems.length}</span> Shorts auf freie Slots innerhalb der nächsten 12 Monate.</>
                                    : 'Auto-Verteilung gesperrt: Upload-Post-Kalender bitte erneut synchronisieren.'}
                                </div>
                                <button
                                  type="button"
                                  onClick={handleAutoAssignSelectedDrafts}
                                  disabled={!vendorCalendarComplete || !(selectedPendingItemIds.length || filteredPendingItems.length)}
                                  className="inline-flex items-center gap-2 rounded-xl border border-amber-300/40 bg-amber-300/15 px-4 py-2 text-xs font-medium text-amber-50 hover:bg-amber-300/20 disabled:opacity-50"
                                >
                                  <CalendarDays size={14} />
                                  Auswahl automatisch verteilen
                                </button>
                              </div>
                            </div>
                          </div>
                        ) : null}
                      </div>

                      {pendingScheduleStatus ? (
                        <div className={`rounded-xl border px-3 py-2 text-sm ${
                          pendingScheduleStatus.type === 'success'
                            ? 'border-green-500/20 bg-green-500/10 text-green-200'
                            : pendingScheduleStatus.type === 'warning'
                              ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                              : pendingScheduleStatus.type === 'info'
                                ? 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100'
                                : 'border-red-500/20 bg-red-500/10 text-red-200'
                        }`}>
                          {pendingScheduleStatus.message}
                        </div>
                      ) : null}

                      {pendingOperationProgress ? (
                        <div className={`rounded-xl border px-3 py-3 ${
                          pendingOperationProgress.active
                            ? 'border-cyan-400/25 bg-cyan-400/10 text-cyan-50'
                            : pendingOperationProgress.failedCount > 0
                              ? 'border-amber-400/25 bg-amber-400/10 text-amber-50'
                              : 'border-emerald-400/25 bg-emerald-400/10 text-emerald-50'
                        }`}>
                          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                            <span className="font-semibold">
                              {pendingOperationProgress.active ? 'Sammel-Scheduling läuft' : 'Sammel-Scheduling abgeschlossen'}
                            </span>
                            <span className="tabular-nums">
                              {pendingOperationProgress.processedCount}/{pendingOperationProgress.totalCount} verarbeitet
                            </span>
                          </div>
                          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/30">
                            <div
                              className={`h-full rounded-full transition-all duration-500 ${pendingOperationProgress.active ? 'bg-cyan-300' : 'bg-emerald-300'}`}
                              style={{ width: `${pendingOperationProgress.percent}%` }}
                            />
                          </div>
                          <div className="mt-2 text-xs opacity-80">
                            {pendingOperationProgress.activeCount > 0 ? `${pendingOperationProgress.activeCount} Jobs aktiv` : 'Keine Jobs mehr aktiv'}
                            {pendingOperationProgress.failedCount > 0 ? ` · ${pendingOperationProgress.failedCount} fehlgeschlagen` : ''}
                            {' · '}Der Kalender kann währenddessen weiter benutzt werden.
                          </div>
                          {!pendingOperationProgress.active && onRefresh ? (
                            <button
                              type="button"
                              onClick={onRefresh}
                              className="mt-3 inline-flex items-center gap-2 rounded-lg border border-white/15 bg-white/8 px-3 py-1.5 text-xs font-medium text-white hover:bg-white/12"
                            >
                              <RefreshCcw size={13} />
                              Kalender jetzt aktualisieren
                            </button>
                          ) : null}
                        </div>
                      ) : null}

                      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-400/20 bg-amber-400/8 px-3 py-3 text-sm text-amber-100">
                        <div>
                          <div className="font-semibold">Gelbe Drafts gesammelt schedulen</div>
                          <div className="mt-1 text-xs text-amber-100/80">Erst ziehen und feinjustieren, dann in einem Schwung Upload-Post starten.</div>
                        </div>
                        <button
                          type="button"
                          onClick={handleScheduleAssignedDrafts}
                          disabled={!assignedDraftCount || pendingScheduleBusy || pendingOperationProgress?.active}
                          className="inline-flex items-center gap-2 rounded-xl border border-amber-300/40 bg-amber-300/15 px-4 py-2 text-sm font-medium text-amber-50 hover:bg-amber-300/20 disabled:opacity-50"
                        >
                          {(pendingScheduleBusy || pendingOperationProgress?.active) ? <Loader2 size={15} className="animate-spin" /> : <CalendarDays size={15} />}
                          {pendingScheduleBusy
                            ? 'Scheduling wird gestartet...'
                            : pendingOperationProgress?.active
                              ? `${pendingOperationProgress.processedCount}/${pendingOperationProgress.totalCount} verarbeitet`
                              : assignedDraftCount
                                ? `${assignedDraftCount} zugewiesene Shorts schedulen`
                                : 'Nichts zu schedulen'}
                        </button>
                      </div>

                      <div className="space-y-3">
                        {!groupedPendingItems.length ? (
                          <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-4 text-sm text-zinc-500">
                            Keine offenen Shorts für den aktuellen Filter.
                          </div>
                        ) : null}
                        {groupedPendingItems.map((group) => {
                          const collapsed = pendingGroupState[group.jobId] === true;
                          return (
                            <div key={group.jobId} className="rounded-xl border border-white/10 bg-black/20">
                              <button
                                type="button"
                                onClick={() => setPendingGroupState((prev) => ({ ...prev, [group.jobId]: !collapsed }))}
                                className="flex w-full items-center justify-between gap-3 px-3 py-3 text-left"
                              >
                                <div>
                                  <div className="text-sm font-semibold text-white">{group.label}</div>
                                  <div className="mt-1 text-xs text-zinc-500">{group.items.length} Shorts · {group.items.filter((item) => item.visual_status === 'assigned').length} gelb zugeordnet</div>
                                </div>
                                <ChevronDown size={16} className={`text-zinc-400 transition-transform ${collapsed ? '' : 'rotate-180'}`} />
                              </button>
                              {!collapsed ? (
                                <div className="border-t border-white/10 px-3 py-3 space-y-2">
                                  {group.items.map((item) => {
                                    const isSelected = selectedEntryKey === item.entryKey;
                                    const isChecked = selectedPendingItemIds.includes(item.id);
                                    return (
                                      <button
                                        key={item.id}
                                        type="button"
                                        draggable
                                        onDragStart={(event) => {
                                          const dragIds = isChecked ? selectedPendingItemIds : [item.id];
                                          const payload = encodeDragPayload({ kind: 'pending', id: item.id, ids: dragIds });
                                          event.dataTransfer.effectAllowed = 'move';
                                          event.dataTransfer.setData('text/plain', payload);
                                          setDraggedPayload(payload);
                                        }}
                                        onDragEnd={() => setDraggedPayload('')}
                                        onClick={() => setSelectedEntryKey(item.entryKey)}
                                        className={`w-full rounded-xl border px-3 py-2.5 text-left transition-colors ${resolveStatusStyle(item.visual_status)} ${isSelected ? 'ring-1 ring-white/30' : ''}`}
                                      >
                                        <div className="flex items-start justify-between gap-3">
                                          <div className="flex min-w-0 items-start gap-3">
                                            <input
                                              type="checkbox"
                                              checked={isChecked}
                                              onChange={(event) => {
                                                event.stopPropagation();
                                                togglePendingSelection(item.id, event.target.checked);
                                              }}
                                              onClick={(event) => event.stopPropagation()}
                                              className="mt-1 h-4 w-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                            />
                                            <div className="min-w-0">
                                              <div className="truncate text-sm font-semibold">{item.title || item.clip_label}</div>
                                              <div className="mt-1 text-[11px] opacity-80">
                                                {item.visual_status === 'assigned'
                                                  ? `Gelb zugeordnet: ${formatDateTimeInputValue(item.assigned_scheduled_date).replace('T', ' ')}`
                                                  : item.status === 'failed'
                                                    ? 'Posting fehlgeschlagen, noch nicht veroeffentlicht'
                                                    : 'Gerendert, noch nicht gescheduled'}
                                              </div>
                                            </div>
                                          </div>
                                          {item.visual_status === 'assigned' ? (
                                            <button
                                              type="button"
                                              onClick={(event) => {
                                                event.stopPropagation();
                                                handleUnassignPendingItem(item.id);
                                              }}
                                              className="shrink-0 rounded-lg border border-amber-300/30 bg-amber-300/10 px-2 py-1 text-[10px] uppercase tracking-wide text-amber-50 hover:bg-amber-300/20"
                                            >
                                              Lösen
                                            </button>
                                          ) : null}
                                        </div>
                                      </button>
                                    );
                                  })}
                                </div>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <div className="flex w-full min-h-0 flex-col xl:w-[460px]">
            <div className="border-b border-white/10 px-4 py-3 md:px-5">
              <h3 className="text-sm font-semibold text-white">Eintrag bearbeiten</h3>
              <p className="mt-1 text-xs text-zinc-500">
                Persistierte Slots direkt aendern. Gelbe Drafts nur lokal zuordnen, previewen und bei Bedarf Titel/Beschreibung anpassen.
              </p>
            </div>
            <div className="flex-1 overflow-y-auto p-4 md:px-5 md:py-4 custom-scrollbar">
              {selectedEntry ? (
                <div className="space-y-4">
                  <div className="overflow-hidden rounded-2xl border border-white/10 bg-black/20">
                    {selectedPreviewUrl ? (
                      <video src={selectedPreviewUrl} controls className="aspect-[9/16] w-full bg-black object-contain" />
                    ) : remotePreviewBusyKey && selectedEvent?.id === remotePreviewBusyKey ? (
                      <div className="flex aspect-[9/16] items-center justify-center gap-2 bg-black text-sm text-zinc-400">
                        <Loader2 size={16} className="animate-spin" />
                        Upload-Post Preview wird geladen
                      </div>
                    ) : (
                      <div className="flex aspect-[9/16] items-center justify-center bg-black px-6 text-center text-sm text-zinc-500">
                        {selectedEvent && !selectedEvent.has_local_media
                          ? (remotePreviewErrors[selectedEvent.id] || 'Kein Preview verfuegbar')
                          : 'Kein Preview verfuegbar'}
                      </div>
                    )}
                    <div className="border-t border-white/10 px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="text-sm font-semibold text-white">{selectedEntry.clip_label}</div>
                        <span className={`inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] ${selectedMediaBadge.className}`}>
                          <SelectedMediaIcon size={11} />
                          {selectedMediaBadge.shortLabel}
                        </span>
                      </div>
                      <div className="mt-1 text-[11px] text-zinc-500">{selectedEntry.job_label}</div>
                    </div>
                  </div>

                  <div className={`rounded-xl border px-3 py-2 text-xs ${resolveStatusStyle(selectedEntry.kind === 'pending' ? selectedEntry.visual_status : selectedEntry.status)}`}>
                    <div className="flex items-center gap-2 font-semibold uppercase tracking-wide">
                      <span>{selectedEntry.kind === 'pending' ? (selectedEntry.visual_status === 'assigned' ? 'Zugeordnet' : selectedEntry.status_label || 'Offen') : selectedEntry.status}</span>
                      {selectedEvent?.is_rescheduled ? <RefreshCcw size={12} /> : null}
                    </div>
                    <div className="mt-1 text-[11px] opacity-90">
                      {selectedEntry.kind === 'pending'
                        ? `${selectedPendingItem?.active_version_label || 'Rendered'} · Erfolgreich ${selectedPendingItem?.success_count || 0} · Fehlgeschlagen ${selectedPendingItem?.failure_count || 0}`
                        : `Erfolgreich ${selectedEvent?.success_count || 0} · Fehlgeschlagen ${selectedEvent?.failure_count || 0} · Offen ${selectedEvent?.pending_count || 0}`}
                    </div>
                    <div className="mt-1 text-[11px] opacity-90">
                      Medium: {selectedMediaBadge.label}
                    </div>
                  </div>

                  <div>
                    <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Datum & Uhrzeit</label>
                    <input
                      type="datetime-local"
                      value={editorState.scheduled_date}
                      onChange={(event) => {
                        const nextValue = event.target.value;
                        setEditorState((prev) => ({ ...prev, scheduled_date: nextValue }));
                        if (selectedPendingItem) {
                          const nextIso = parseDateInputToIso(nextValue);
                          if (nextIso) handleAssignPendingItem(selectedPendingItem, nextIso);
                        }
                      }}
                      className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                    />
                  </div>

                  <div>
                    <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Titel</label>
                    <input
                      type="text"
                      value={editorState.title}
                      onChange={(event) => setEditorState((prev) => ({ ...prev, title: event.target.value }))}
                      className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                    />
                  </div>

                  <div>
                    <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Beschreibung</label>
                    <textarea
                      value={editorState.description}
                      onChange={(event) => setEditorState((prev) => ({ ...prev, description: event.target.value }))}
                      rows={4}
                      className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                    />
                  </div>

                  {selectedEvent ? (
                    <>
                      <div>
                        <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Erster Kommentar</label>
                        <textarea
                          value={editorState.first_comment}
                          onChange={(event) => setEditorState((prev) => ({ ...prev, first_comment: event.target.value }))}
                          rows={3}
                          className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-500/40"
                        />
                      </div>

                      <div>
                        <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-zinc-400">Plattformen</label>
                        <div className="grid grid-cols-2 gap-2">
                          {SOCIAL_PLATFORM_OPTIONS.map((platform) => {
                            const checked = editorState.platforms.includes(platform.key);
                            return (
                              <label key={platform.key} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-200">
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={(event) => {
                                    setEditorState((prev) => ({
                                      ...prev,
                                      platforms: event.target.checked
                                        ? [...prev.platforms, platform.key]
                                        : prev.platforms.filter((item) => item !== platform.key),
                                    }));
                                  }}
                                  className="h-4 w-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                />
                                {platform.label}
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="rounded-xl border border-amber-400/20 bg-amber-400/8 px-3 py-3 text-xs text-amber-100">
                      Plattformen und Post-Optionen fuer Drafts kommen aus dem Sammel-Schedule unten im Kalenderbereich.
                    </div>
                  )}

                  {selectedEvent?.platform_links?.length ? (
                    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Vorhandene Links</div>
                      <div className="space-y-2 text-sm">
                        {selectedEvent.platform_links.map((link) => (
                          <a key={`${link.platform}-${link.url}`} href={link.url} target="_blank" rel="noreferrer" className="block truncate text-cyan-300 hover:text-cyan-200">
                            {PLATFORM_LABELS[link.platform] || link.platform}: {link.url}
                          </a>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-5 text-sm text-zinc-500">
                  Kalender-Eintrag oder Draft auswaehlen.
                </div>
              )}
            </div>

            <div className="border-t border-white/10 px-4 py-4 md:px-5">
              {actionError ? (
                <div className="mb-3 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                  {actionError}
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {selectedEvent ? (
                  <>
                    <button
                      type="button"
                      onClick={handleReschedule}
                      disabled={!selectedEvent || selectedEvent?.is_blocked_slot || !!savingAction || (!(selectedEvent?.can_recreate === false || selectedEvent?.event_source === 'vendor_only') && !onRescheduleEvent) || ((selectedEvent?.can_recreate === false || selectedEvent?.event_source === 'vendor_only') && !onSaveEvent)}
                      className="inline-flex items-center justify-center gap-2 rounded-xl border border-fuchsia-500/30 bg-fuchsia-500/10 px-4 py-2.5 text-sm font-medium text-fuchsia-100 hover:bg-fuchsia-500/15 disabled:opacity-50"
                    >
                      {savingAction.startsWith('reschedule:') ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
                      {selectedEvent?.can_recreate === false || selectedEvent?.event_source === 'vendor_only'
                        ? 'Reschedule / verschieben'
                        : 'Reschedule / neu hochladen'}
                    </button>
                    <button
                      type="button"
                      onClick={handleEditorSave}
                      disabled={!selectedEvent || selectedEvent?.is_blocked_slot || !!savingAction}
                      className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-600 to-sky-600 px-4 py-2.5 text-sm font-semibold text-white hover:from-cyan-500 hover:to-sky-500 disabled:opacity-50"
                    >
                      {savingAction.startsWith('save:') ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                      Speichern / neu planen
                    </button>
                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={!selectedEvent || selectedEvent?.is_blocked_slot || !!savingAction}
                      className="inline-flex items-center justify-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-sm font-medium text-red-200 hover:bg-red-500/15 disabled:opacity-50"
                    >
                      {savingAction.startsWith('delete:') ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                      Loeschen
                    </button>
                  </>
                ) : selectedPendingItem ? (
                  <>
                    <button
                      type="button"
                      onClick={handleEditorSave}
                      disabled={!selectedPendingItem || !!savingAction || !onSavePendingItem}
                      className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-600 to-sky-600 px-4 py-2.5 text-sm font-semibold text-white hover:from-cyan-500 hover:to-sky-500 disabled:opacity-50"
                    >
                      {savingAction.startsWith('save:') ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                      Clip speichern
                    </button>
                    <button
                      type="button"
                      onClick={() => handleUnassignPendingItem(selectedPendingItem.id)}
                      disabled={!selectedPendingItem?.assigned_scheduled_date}
                      className="inline-flex items-center justify-center gap-2 rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-2.5 text-sm font-medium text-amber-100 hover:bg-amber-400/15 disabled:opacity-50"
                    >
                      <Trash2 size={15} />
                      Zuordnung loesen
                    </button>
                  </>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
