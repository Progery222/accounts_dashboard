export interface TikTokVideo {
  id: string;
  description: string;
  cover: string;
  play_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  created_at: number;
}

export interface TikTokProfile {
  username: string;
  nickname: string;
  avatar: string;
  bio: string;
  verified: boolean;
  follower_count: number;
  like_count: number;
  video_count: number;
  videos: TikTokVideo[];
}
