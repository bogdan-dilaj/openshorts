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
    label: 'Regular Reel',
    description: 'Normal Reel for followers immediately.',
  },
  {
    value: 'TRIAL_REELS_SHARE_TO_FOLLOWERS_IF_LIKED',
    label: 'Trial Reel Auto-Share',
    description: 'Show to non-followers first. Instagram shares later if performance is strong.',
  },
  {
    value: 'TRIAL_REELS_DONT_SHARE_TO_FOLLOWERS',
    label: 'Trial Reel Only',
    description: 'Show only to non-followers until you manually share it later.',
  },
];

export const TIKTOK_POST_MODES = [
  {
    value: 'DIRECT_POST',
    label: 'Direct Post',
    description: 'Publish directly to the TikTok account.',
  },
  {
    value: 'MEDIA_UPLOAD',
    label: 'Draft / Inbox',
    description: 'Upload to TikTok inbox so the user finishes publishing in the TikTok app.',
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
