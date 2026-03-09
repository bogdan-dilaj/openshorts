export const SOCIAL_PLATFORM_OPTIONS = [
  { key: 'tiktok', label: 'TikTok' },
  { key: 'instagram', label: 'Instagram' },
  { key: 'youtube', label: 'YouTube Shorts' },
  { key: 'facebook', label: 'Facebook' },
  { key: 'x', label: 'X' },
  { key: 'threads', label: 'Threads' },
  { key: 'pinterest', label: 'Pinterest' },
];

export const INSTAGRAM_SHARE_MODES = [
  {
    value: 'CUSTOM',
    label: 'Normales Reel',
    description: 'Normales Reel, sofort für Follower sichtbar.',
  },
  {
    value: 'TRIAL_REELS_SHARE_TO_FOLLOWERS_IF_LIKED',
    label: 'Trial Reel mit Auto-Share',
    description: 'Erst für Nicht-Follower. Bei guter Performance teilt Instagram später an Follower.',
  },
  {
    value: 'TRIAL_REELS_DONT_SHARE_TO_FOLLOWERS',
    label: 'Nur Trial Reel',
    description: 'Nur für Nicht-Follower sichtbar, bis du es später manuell teilst.',
  },
];

export const TIKTOK_POST_MODES = [
  {
    value: 'DIRECT_POST',
    label: 'Direkt posten',
    description: 'Direkt auf dem TikTok-Konto veröffentlichen.',
  },
  {
    value: 'MEDIA_UPLOAD',
    label: 'Entwurf / Inbox',
    description: 'In die TikTok-Inbox hochladen, damit der Nutzer den Post in TikTok finalisiert.',
  },
];

export const DEFAULT_SOCIAL_POST_SETTINGS = {
  platforms: {
    tiktok: true,
    instagram: true,
    youtube: true,
    facebook: false,
    x: false,
    threads: false,
    pinterest: false,
  },
  instagramShareMode: 'CUSTOM',
  tiktokPostMode: 'DIRECT_POST',
  tiktokIsAigc: false,
  facebookPageId: '',
  pinterestBoardId: '',
};
