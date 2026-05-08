// Mock data + helpers shared across screens.

const TOTAL = {
  followers: { value: 150, delta: 33 },
  views: { value: 232600, delta: 12500 },
  likes: { value: 3700, delta: 151 },
  posts: { value: 1700, delta: 93 },
  accounts: 163,
};

const PLATFORMS = [
  { id: 'tiktok',    label: 'TikTok',     color: '#ff2d55', share: 0.62, accounts: 101 },
  { id: 'instagram', label: 'Instagram',  color: '#ec4899', share: 0.18, accounts: 29 },
  { id: 'youtube',   label: 'YouTube',    color: '#ff4444', share: 0.09, accounts: 14 },
  { id: 'twitter',   label: 'X (Twitter)',color: '#dddddd', share: 0.05, accounts: 9 },
  { id: 'threads',   label: 'Threads',    color: '#9aa0aa', share: 0.04, accounts: 7 },
  { id: 'telegram',  label: 'Telegram',   color: '#26a5e4', share: 0.02, accounts: 3 },
];

const PROFILES = [
  { id: 'fil',     label: 'Фил',         color: '#4ade80', accounts: 90 },
  { id: 'sport',   label: 'Спорт Завод', color: '#fb923c', accounts: 14 },
  { id: 'music',   label: 'Музыка',      color: '#ec4899', accounts: 58 },
];

const ACCOUNTS = [
  { name: 'thecapitolverdict', handle: '@thecapitolverdict', platform: 'tiktok',    profile: 'fil',   followers: null, views: 14300, dViews: 1200, likes: 222, dLikes: 29, posts: 24, dPosts: 2,  updated: '07.05, 14:05' },
  { name: 'capital.watch4',    handle: '@capital.watch4',    platform: 'tiktok',    profile: 'fil',   followers: null, views: 8800,  dViews: 545,  likes: 15,  dLikes: 0,  posts: 21, dPosts: 2,  updated: '07.05, 13:50' },
  { name: 'yllazenspace',      handle: '@yllazenspace',      platform: 'tiktok',    profile: 'music', followers: null, views: 8700,  dViews: 589,  likes: 379, dLikes: 33, posts: 31, dPosts: 0,  updated: '07.05, 10:43' },
  { name: 'yllazenx',          handle: '@yllazenx',          platform: 'tiktok',    profile: 'music', followers: 1,    views: 8100,  dViews: 402,  likes: 188, dLikes: 0,  posts: 23, dPosts: 1,  updated: '07.05, 13:33' },
  { name: 'yllazen.music',     handle: '@yllazen.music',     platform: 'tiktok',    profile: 'music', followers: null, views: 8000,  dViews: 125,  likes: 101, dLikes: 1,  posts: 24, dPosts: 0,  updated: '07.05, 06:26' },
  { name: 'yllazenera',        handle: '@yllazenera',        platform: 'tiktok',    profile: 'music', followers: null, views: 7700,  dViews: 269,  likes: 99,  dLikes: 1,  posts: 31, dPosts: 2,  updated: '07.05, 06:25' },
  { name: 'yllazen.officiall', handle: '@yllazen.officiall', platform: 'tiktok',    profile: 'music', followers: null, views: 6800,  dViews: 97,   likes: 178, dLikes: 4,  posts: 27, dPosts: 1,  updated: '07.05, 06:27' },
  { name: 'yllazensound',      handle: '@yllazensound',      platform: 'tiktok',    profile: 'music', followers: null, views: 6700,  dViews: 583,  likes: 145, dLikes: 3,  posts: 22, dPosts: 1,  updated: '07.05, 06:24' },
  { name: 'saint_f1_news',     handle: '@saint_f1_news',     platform: 'tiktok',    profile: 'sport', followers: 5,    views: 6500,  dViews: 65,   likes: 454, dLikes: -1, posts: 11, dPosts: 1,  updated: '07.05, 06:08' },
  { name: 'yllazenlab',        handle: '@yllazenlab',        platform: 'tiktok',    profile: 'music', followers: 2,    views: 6200,  dViews: 21,   likes: 224, dLikes: 1,  posts: 30, dPosts: 0,  updated: '07.05, 06:25' },
  { name: 'phil.cuts',         handle: '@phil.cuts',         platform: 'tiktok',    profile: 'fil',   followers: 4,    views: 5900,  dViews: 0,    likes: 26,  dLikes: 0,  posts: 11, dPosts: 0,  updated: '07.05, 13:42' },
  { name: 'phil.highlights6',  handle: '@phil.highlights6',  platform: 'tiktok',    profile: 'fil',   followers: 5,    views: 5400,  dViews: 1,    likes: 32,  dLikes: 0,  posts: 11, dPosts: 0,  updated: '07.05, 13:41' },
  { name: 'phil.redpill',      handle: '@phil.redpill',      platform: 'instagram', profile: 'fil',   followers: 12,   views: 4800,  dViews: 354,  likes: 48,  dLikes: 6,  posts: 18, dPosts: 1,  updated: '07.05, 12:18' },
  { name: 'phil.daily',        handle: '@phil.daily',        platform: 'youtube',   profile: 'fil',   followers: 8,    views: 4100,  dViews: 87,   likes: 22,  dLikes: 1,  posts: 9,  dPosts: 0,  updated: '07.05, 09:55' },
];

const POSTS = [
  { handle: '@phil.redpill',     platform: 'instagram', date: '06.05.26', text: 'Uncensored truth. Search "Phil Godlewski" on Rumble.', delta: 354, views: 370, likes: 0,  er: 0.0 },
  { handle: '@yllazenspace',     platform: 'tiktok',    date: '06.05.26', text: 'why is nobody talking about this — Ylla Zen — Light It Up', delta: 279, views: 324, likes: 17, er: 5.3 },
  { handle: '@yllazenspace',     platform: 'tiktok',    date: '06.05.26', text: 'why is nobody talking about this — Ylla Zen — Light It Up', delta: 202, views: 210, likes: 9,  er: 4.3 },
  { handle: '@yllazenera',       platform: 'tiktok',    date: '06.05.26', text: 'why is nobody talking about this save this one — Ylla Zen — You', delta: 179, views: 191, likes: 0,  er: 0.0 },
  { handle: '@capital.watch4',   platform: 'tiktok',    date: '06.05.26', text: 'Uncensored truth. Search "Phil Godlewski" on Rumble.', delta: 135, views: 274, likes: 0,  er: 0.0 },
  { handle: '@yllazensound',     platform: 'tiktok',    date: '06.05.26', text: "underrated banger alert — 'Secret.' by Ylla Zen", delta: 131, views: 317, likes: 2,  er: 0.6 },
  { handle: '@thecapitolverdict',platform: 'instagram', date: '05.05.26', text: 'Uncensored truth. Search "Phil Godlewski" on Rumble.', delta: 127, views: 387, likes: 0,  er: 0.0 },
  { handle: '@yllazen.music',    platform: 'tiktok',    date: '06.05.26', text: "POV: you just found Ylla Zen's 'Silence' before everyone else", delta: 121, views: 318, likes: 3,  er: 0.9 },
];

// 24h sparkline samples
const TREND_24H = [120,140,135,180,210,250,230,260,310,360,340,380,420,460,440,490,520,580,610,640,680,720,760,810];
const TREND_7D  = [3200,3800,4100,4400,4800,5200,5600];

function fmt(n){
  if (n == null) return '—';
  if (Math.abs(n) >= 1000000) return (n/1000000).toFixed(1).replace('.0','') + 'M';
  if (Math.abs(n) >= 1000) return (n/1000).toFixed(1).replace('.0','') + 'K';
  return String(n);
}
function fmtSign(n){ if (n == null) return ''; return (n > 0 ? '+' : '') + fmt(n); }

const PLATFORM_META = Object.fromEntries(PLATFORMS.map(p => [p.id, p]));
const PROFILE_META  = Object.fromEntries(PROFILES.map(p  => [p.id, p]));

Object.assign(window, { TOTAL, PLATFORMS, PROFILES, ACCOUNTS, POSTS, TREND_24H, TREND_7D, fmt, fmtSign, PLATFORM_META, PROFILE_META });
